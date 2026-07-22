import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_user, require_roles
from app.db.database import get_db
from app.models.order import (
    DiscountType,
    Order,
    OrderItem,
    OrderSageSyncStatus,
    OrderStatus,
)
from app.models.product import Product
from app.models.shop import Shop, ShopApprovalStatus
from app.models.user import User
from app.schemas.order import (
    AssistedOrderCreate,
    OrderCreate,
    OrderItemCreate,
    OrderListResponse,
    OrderResponse,
    OrderSummaryResponse,
    SageSyncedRequest,
    SalesOrderDetailResponse,
)


router = APIRouter(prefix="/orders", tags=["orders"])
admin_router = APIRouter(prefix="/admin/orders", tags=["admin orders"])
money_unit = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(money_unit, rounding=ROUND_HALF_UP)


def get_approved_shop_or_404(shop_id: int, db: Session) -> Shop:
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop not found",
        )
    if shop.approval_status != ShopApprovalStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shop must be approved before orders can be placed",
        )
    return shop


def get_current_user_approved_shop(current_user: User, db: Session) -> Shop:
    shop = db.query(Shop).filter(Shop.user_id == current_user.id).first()
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user does not have a registered shop",
        )
    if current_user.role == "shop_owner" and not shop.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending admin approval.",
        )
    return get_approved_shop_or_404(shop.id, db)


def aggregate_items(items: list[OrderItemCreate]) -> dict[int, int]:
    aggregated: dict[int, int] = defaultdict(int)
    for item in items:
        aggregated[item.product_id] += item.quantity
    return dict(aggregated)


def build_order_items(
    db: Session,
    items: list[OrderItemCreate],
    is_assisted: bool = False,
) -> tuple[list[OrderItem], Decimal]:
    subtotal = Decimal("0.00")
    order_items: list[OrderItem] = []

    product_vats = {}
    for item in items:
        if is_assisted and item.vat_rate is not None:
            product_vats[item.product_id] = item.vat_rate

    for product_id, quantity in aggregate_items(items).items():
        product = (
            db.query(Product)
            .filter(Product.id == product_id, Product.is_active.is_(True))
            .with_for_update()
            .first()
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {product_id} not found",
            )

        unit_price = quantize_money(product.price)
        line_total = quantize_money(unit_price * quantity)
        subtotal += line_total

        vat_rate = product_vats.get(product.id)
        if vat_rate is None:
            vat_rate = float(product.vat_rate) if getattr(product, "vat_rate", None) is not None else 20.0

        vat_amount = float(line_total) * (vat_rate / 100.0)

        order_items.append(
            OrderItem(
                product_id=product.id,
                product_code=product.product_code,
                product_name=product.product_name,
                unit_price=unit_price,
                quantity=quantity,
                line_total=line_total,
                vat_rate=vat_rate,
                vat_amount=vat_amount,
            )
        )

    return order_items, quantize_money(subtotal)


def calculate_discount(
    subtotal: Decimal,
    discount_type: DiscountType | None,
    discount_value: Decimal | None,
) -> tuple[str | None, Decimal | None, Decimal]:
    if discount_type is None and discount_value is None:
        return None, None, Decimal("0.00")
    if discount_type is None or discount_value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="discount_type and discount_value must be provided together",
        )

    discount_value = quantize_money(discount_value)
    if discount_type == DiscountType.FIXED:
        if discount_value > subtotal:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fixed discount cannot exceed subtotal",
            )
        return discount_type.value, discount_value, discount_value

    if discount_value > Decimal("100.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Percentage discount must be between 0 and 100",
        )

    discount_amount = quantize_money(subtotal * discount_value / Decimal("100"))
    return discount_type.value, discount_value, discount_amount


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def generate_order_number(order_id: int) -> str:
    return f"SO-{order_id:06d}"


def create_order_record(
    db: Session,
    shop: Shop,
    current_user: User,
    items: list[OrderItemCreate],
    discount_type: DiscountType | None = None,
    discount_value: Decimal | None = None,
    customer_reference: str | None = None,
    internal_notes: str | None = None,
) -> Order:
    try:
        is_assisted = current_user.role in ("admin", "salesperson")
        order_items, subtotal = build_order_items(db, items, is_assisted=is_assisted)
        stored_discount_type, stored_discount_value, discount_amount = calculate_discount(
            subtotal,
            discount_type,
            discount_value,
        )
        final_total = quantize_money(subtotal - discount_amount)
        total_vat = sum(item.vat_amount for item in order_items)

        order = Order(
            shop_id=shop.id,
            account_ref=shop.account_ref,
            created_by_user_id=current_user.id,
            created_by_role=current_user.role,
            salesperson_id=current_user.id if current_user.role == "salesperson" else None,
            customer_reference=clean_optional_text(customer_reference),
            internal_notes=clean_optional_text(internal_notes),
            subtotal=subtotal,
            discount_type=stored_discount_type,
            discount_value=stored_discount_value,
            discount_amount=discount_amount,
            final_total=final_total,
            total_vat=total_vat,
            items=order_items,
        )

        db.add(order)
        db.flush()
        order.order_number = generate_order_number(order.id)
        db.commit()
        db.refresh(order)
        return order
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def ensure_order_access(order: Order, current_user: User, db: Session) -> None:
    if current_user.role == "admin":
        return
    if current_user.role == "salesperson":
        if order.salesperson_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return

    shop = db.query(Shop).filter(Shop.user_id == current_user.id).first()
    if not shop or order.shop_id != shop.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )


def build_sales_order_detail_response(order: Order) -> SalesOrderDetailResponse:
    return SalesOrderDetailResponse(
        order={
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "created_at": order.created_at,
            "created_by_role": order.created_by_role,
            "customer_reference": order.customer_reference,
            "subtotal": order.subtotal,
            "discount_type": order.discount_type,
            "discount_value": order.discount_value,
            "discount_amount": order.discount_amount,
            "final_total": order.final_total,
            "total_vat": order.total_vat,
            "sage_sync_status": order.sage_sync_status,
            "salesperson_id": order.salesperson_id,
            "sage_order_number": order.sage_order_number,
            "sync_notes": order.sync_notes,
        },
        shop={
            "id": order.shop.id,
            "company_name": order.shop.company_name,
            "phone_number": order.shop.phone_number,
            "address": order.shop.address,
            "postcode": order.shop.postcode,
            "city": order.shop.city,
        },
        items=[
            {
                "product_code": item.product_code,
                "product_name": item.product_name,
                "unit_price": item.unit_price,
                "quantity": item.quantity,
                "line_total": item.line_total,
                "vat_rate": item.vat_rate,
                "vat_amount": item.vat_amount,
            }
            for item in order.items
        ],
    )


def validate_order_status_filter(order_status: str | None) -> str | None:
    if order_status is None:
        return None

    allowed_statuses = {OrderStatus.PLACED.value, OrderStatus.CANCELLED.value}
    if order_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be one of: placed, cancelled",
        )

    return order_status


def validate_sage_sync_status_filter(sage_sync_status: str | None) -> str | None:
    if sage_sync_status is None:
        return None

    allowed_statuses = {
        OrderSageSyncStatus.PENDING.value,
        OrderSageSyncStatus.PROCESSING.value,
        OrderSageSyncStatus.SYNCED.value,
        OrderSageSyncStatus.FAILED.value,
    }
    if sage_sync_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sage_sync_status must be one of: pending, processing, synced, failed",
        )

    return sage_sync_status


def get_order_date_range(
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_from cannot be after date_to",
        )

    start_at = datetime.combine(date_from, time.min) if date_from else None
    end_before = (
        datetime.combine(date_to + timedelta(days=1), time.min) if date_to else None
    )
    return start_at, end_before


def apply_order_date_filters(
    query,
    date_from: date | None,
    date_to: date | None,
):
    start_at, end_before = get_order_date_range(date_from, date_to)
    if start_at is not None:
        query = query.filter(Order.created_at >= start_at)
    if end_before is not None:
        query = query.filter(Order.created_at < end_before)
    return query


def apply_order_list_filters(
    query,
    search: str | None,
    order_status: str | None,
    date_from: date | None,
    date_to: date | None,
    sage_sync_status: str | None = None,
):
    status_filter = validate_order_status_filter(order_status)
    sage_sync_status_filter = validate_sage_sync_status_filter(sage_sync_status)
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.join(Shop).filter(
            or_(
                Order.order_number.ilike(search_pattern),
                Order.customer_reference.ilike(search_pattern),
                Shop.company_name.ilike(search_pattern),
                Shop.postcode.ilike(search_pattern),
                Shop.city.ilike(search_pattern),
            )
        )
    if status_filter is not None:
        query = query.filter(Order.status == status_filter)
    if sage_sync_status_filter is not None:
        query = query.filter(Order.sage_sync_status == sage_sync_status_filter)
    return apply_order_date_filters(query, date_from, date_to)


@admin_router.get(
    "/summary",
    response_model=OrderSummaryResponse,
    summary="Get admin order summary",
    description="Admin-only dashboard summary for orders, with optional date filtering.",
)
def get_admin_order_summary(
    current_user: Annotated[User, Depends(require_roles("admin", "salesperson"))],
    db: Annotated[Session, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> OrderSummaryResponse:
    query = apply_order_date_filters(db.query(Order), date_from, date_to)

    if current_user.role == "salesperson":
        query = query.filter(Order.salesperson_id == current_user.id)

    total_orders = query.count()
    placed_orders = query.filter(Order.status == OrderStatus.PLACED.value).count()
    cancelled_orders = query.filter(Order.status == OrderStatus.CANCELLED.value).count()
    pending_sage_sync = query.filter(Order.sage_sync_status == "pending").count()

    subtotal_total = query.with_entities(func.coalesce(func.sum(Order.subtotal), 0)).scalar()
    discount_total = query.with_entities(
        func.coalesce(func.sum(Order.discount_amount), 0)
    ).scalar()
    final_total = query.with_entities(func.coalesce(func.sum(Order.final_total), 0)).scalar()

    return OrderSummaryResponse(
        total_orders=total_orders,
        placed_orders=placed_orders,
        cancelled_orders=cancelled_orders,
        subtotal_total=quantize_money(Decimal(subtotal_total or 0)),
        discount_total=quantize_money(Decimal(discount_total or 0)),
        final_total=quantize_money(Decimal(final_total or 0)),
        pending_sage_sync=pending_sage_sync,
    )


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create shop owner order",
    description="Shop-owner-only endpoint. Creates an order for the current user's approved shop.",
)
def create_shop_owner_order(
    payload: OrderCreate,
    current_user: Annotated[User, Depends(require_roles("shop_owner"))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    shop = get_current_user_approved_shop(current_user, db)
    return create_order_record(
        db,
        shop,
        current_user,
        payload.items,
        customer_reference=payload.customer_reference,
    )


@router.post(
    "/assisted",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create assisted order",
    description="Admin and salesperson endpoint for creating assisted orders for approved shops.",
)
def create_assisted_order(
    payload: AssistedOrderCreate,
    current_user: Annotated[User, Depends(require_roles("admin", "salesperson"))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    shop = get_approved_shop_or_404(payload.shop_id, db)
    return create_order_record(
        db,
        shop,
        current_user,
        payload.items,
        payload.discount_type,
        payload.discount_value,
        payload.customer_reference,
        payload.internal_notes,
    )


@router.patch(
    "/{order_id}/mark-sage-processing",
    response_model=OrderResponse,
    summary="Mark order as processing for Sage",
    description="Admin-only state update. This endpoint does not call Sage.",
)
def mark_order_sage_processing(
    order_id: int,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if order.status != OrderStatus.PLACED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only placed orders can be marked as Sage processing",
        )
    if order.sage_sync_status != OrderSageSyncStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be marked as Sage processing",
        )

    order.sage_sync_status = OrderSageSyncStatus.PROCESSING.value
    db.commit()
    db.refresh(order)
    return order


@router.patch(
    "/{order_id}/mark-sage-failed",
    response_model=OrderResponse,
    summary="Mark order as failed for Sage",
    description="Admin-only state update. This endpoint does not call Sage.",
)
def mark_order_sage_failed(
    order_id: int,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    order.sage_sync_status = OrderSageSyncStatus.FAILED.value
    db.commit()
    db.refresh(order)
    return order


@router.patch(
    "/{order_id}/mark-sage-synced",
    response_model=OrderResponse,
    summary="Record successful Sage Sales Order sync",
    description=(
        "Admin-only state update that records the Sage Sales Order ID. "
        "This endpoint does not call Sage."
    ),
)
def mark_order_sage_synced(
    order_id: int,
    payload: SageSyncedRequest,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if order.status != OrderStatus.PLACED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only placed orders can be marked as Sage synced",
        )

    order.sage_sales_order_id = payload.sage_sales_order_id
    order.sage_sync_status = OrderSageSyncStatus.SYNCED.value
    db.commit()
    db.refresh(order)
    return order


@router.patch(
    "/{order_id}/retry-sage-sync",
    response_model=OrderResponse,
    summary="Retry failed Sage Sales Order sync",
    description=(
        "Admin-only state update that returns a failed Sales Order sync to pending. "
        "This endpoint does not call Sage."
    ),
)
def retry_order_sage_sync(
    order_id: int,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if order.status != OrderStatus.PLACED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cancelled orders cannot be retried for Sage sync",
        )
    if order.sage_sync_status != OrderSageSyncStatus.FAILED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed Sage sync orders can be retried",
        )

    order.sage_sync_status = OrderSageSyncStatus.PENDING.value
    order.sage_sales_order_id = None
    db.commit()
    db.refresh(order)
    return order


@router.patch(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel an order",
    description=(
        "Admin and salesperson can cancel any placed order. "
        "Shop owners can cancel only orders belonging to their own shop."
    ),
)
def cancel_order(
    order_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    try:
        order = (
            db.query(Order)
            .filter(Order.id == order_id)
            .with_for_update()
            .first()
        )
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        ensure_order_access(order, current_user, db)

        if order.status == OrderStatus.CANCELLED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order is already cancelled",
            )
        if order.status != OrderStatus.PLACED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only placed orders can be cancelled",
            )

        for item in order.items:
            product = (
                db.query(Product)
                .filter(Product.id == item.product_id)
                .with_for_update()
                .first()
            )
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unable to restore product {item.product_code}",
                )
            product.quantity += item.quantity

        order.status = OrderStatus.CANCELLED.value
        db.commit()
        db.refresh(order)
        return order
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.get(
    "",
    response_model=OrderListResponse,
    summary="List orders",
    description="Admin and salesperson see all orders. Shop owners see only their own shop orders.",
)
def list_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    status: str | None = None,
    sage_sync_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OrderListResponse:
    query = apply_order_list_filters(
        db.query(Order).options(
            joinedload(Order.salesperson),
            joinedload(Order.items),
            joinedload(Order.shop)
        ),
        search,
        status,
        date_from,
        date_to,
        sage_sync_status,
    )

    if current_user.role == "salesperson":
        query = query.filter(Order.salesperson_id == current_user.id)
    elif current_user.role == "shop_owner":
        shop = db.query(Shop).filter(Shop.user_id == current_user.id).first()
        if not shop:
            return OrderListResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                pages=0,
            )
        query = query.filter(Order.shop_id == shop.id)

    total = query.count()
    pages = (total + page_size - 1) // page_size if total else 0
    items = (
        query.order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return OrderListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/sage-pending",
    response_model=list[SalesOrderDetailResponse],
    summary="List pending Sage sales orders",
    description=(
        "Admin and salesperson can view placed orders awaiting Sage Sales Order sync. "
        "This endpoint does not call Sage."
    ),
)
def list_sage_pending_orders(
    current_user: Annotated[
        User,
        Depends(require_roles("admin", "salesperson")),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> list[SalesOrderDetailResponse]:
    orders = (
        db.query(Order)
        .options(
            joinedload(Order.shop),
            joinedload(Order.items),
        )
        .filter(
            Order.status == OrderStatus.PLACED.value,
            Order.sage_sync_status == OrderSageSyncStatus.PENDING.value,
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    return [build_sales_order_detail_response(order) for order in orders]


@router.get(
    "/export-csv",
    summary="Export orders as CSV",
    description="Admin and salesperson can export matching orders with one row per order item.",
)
def export_orders_csv(
    current_user: Annotated[
        User,
        Depends(require_roles("admin", "salesperson")),
    ],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StreamingResponse:
    query = apply_order_list_filters(
        db.query(Order).options(
            joinedload(Order.shop),
            joinedload(Order.items),
        ),
        search,
        status,
        date_from,
        date_to,
    )
    orders = query.order_by(Order.created_at.desc()).all()

    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "order_number",
            "order_id",
            "order_status",
            "shop_id",
            "name",
            "shop_postcode",
            "created_by_user_id",
            "created_by_role",
            "customer_reference",
            "product_code",
            "product_name",
            "unit_price",
            "quantity",
            "line_total",
            "subtotal",
            "discount_type",
            "discount_value",
            "discount_amount",
            "final_total",
            "sage_sync_status",
            "created_at",
        ]
    )

    for order in orders:
        for item in order.items:
            writer.writerow(
                [
                    order.order_number or "",
                    order.id,
                    order.status,
                    order.shop_id,
                    order.shop.company_name,
                    order.shop.postcode,
                    order.created_by_user_id,
                    order.created_by_role,
                    order.customer_reference or "",
                    item.product_code,
                    item.product_name,
                    f"{item.unit_price:.2f}",
                    item.quantity,
                    f"{item.line_total:.2f}",
                    f"{order.subtotal:.2f}",
                    order.discount_type or "",
                    (
                        f"{order.discount_value:.2f}"
                        if order.discount_value is not None
                        else ""
                    ),
                    f"{order.discount_amount:.2f}",
                    f"{order.final_total:.2f}",
                    order.sage_sync_status,
                    order.created_at.isoformat(),
                ]
            )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="orders_export.csv"',
        },
    )


@router.get(
    "/{order_id}/sales-order-detail",
    response_model=SalesOrderDetailResponse,
    summary="Get sales order details",
    description=(
        "Admin and salesperson can access any sales order. "
        "Shop owners can access only sales orders for their own shop."
    ),
)
def get_sales_order_detail(
    order_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SalesOrderDetailResponse:
    order = (
        db.query(Order)
        .options(
            joinedload(Order.shop),
            joinedload(Order.items),
        )
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    ensure_order_access(order, current_user, db)
    return build_sales_order_detail_response(order)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get order",
    description="Admin and salesperson can access any order. Shop owners can access only their own shop orders.",
)
def get_order(
    order_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    ensure_order_access(order, current_user, db)
    return order
