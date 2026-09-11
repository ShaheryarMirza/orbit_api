import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO, BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
    UpdateOrderPricesRequest,
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
    product_prices = {}
    for item in items:
        if is_assisted:
            if item.vat_rate is not None:
                product_vats[item.product_id] = item.vat_rate
            if item.unit_price is not None:
                product_prices[item.product_id] = quantize_money(item.unit_price)

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

        unit_price = product_prices.get(product.id)
        if unit_price is None:
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

        # Calculate line item VAT and total order VAT on discounted net line amounts (matching Assisted Order Cart)
        subtotal_float = float(subtotal)
        discount_float = float(discount_amount)
        ratio = (subtotal_float - discount_float) / subtotal_float if subtotal_float > 0 else 1.0

        for item in order_items:
            line_gross = float(item.line_total)
            line_net = line_gross * ratio
            item.vat_amount = round(line_net * (item.vat_rate / 100.0), 2)

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
    if current_user.role in ("admin", "root_admin", "salesperson"):
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
    current_user: User = Depends(require_roles("admin", "salesperson")),
    db: Session = Depends(get_db),
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

    active_query = query.filter(Order.status == OrderStatus.PLACED.value)

    subtotal_total = active_query.with_entities(func.coalesce(func.sum(Order.subtotal), 0)).scalar()
    discount_total = active_query.with_entities(
        func.coalesce(func.sum(Order.discount_amount), 0)
    ).scalar()
    final_total = active_query.with_entities(
        func.coalesce(func.sum(Order.final_total + func.coalesce(Order.total_vat, 0)), 0)
    ).scalar()

    return OrderSummaryResponse(
        total_orders=placed_orders,
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
    current_user: User = Depends(require_roles("shop_owner")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin", "salesperson")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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


@router.patch(
    "/{order_id}/prices",
    response_model=SalesOrderDetailResponse,
    summary="Update order line item prices (Admin & Salesperson)",
    description=(
        "Allows staff to update line item unit prices of an existing placed, unsynced order. "
        "Recalculates line totals, subtotal, discount, VAT, and final total in database."
    ),
)
def update_order_prices(
    order_id: int,
    payload: UpdateOrderPricesRequest,
    current_user: User = Depends(require_roles("admin", "salesperson")),
    db: Session = Depends(get_db),
) -> SalesOrderDetailResponse:
    try:
        order = (
            db.query(Order)
            .options(joinedload(Order.shop), joinedload(Order.items))
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

        if order.status != OrderStatus.PLACED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only placed orders can have their prices updated",
            )

        if order.sage_sync_status in ("synced", OrderSageSyncStatus.SYNCED.value, "completed"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update prices for an order that has already been synced with Sage",
            )

        price_map = {item_update.product_id: item_update for item_update in payload.items}

        subtotal = Decimal("0.00")
        for item in order.items:
            if item.product_id in price_map:
                item_update = price_map[item.product_id]
                item.unit_price = quantize_money(item_update.unit_price)
                if item_update.vat_rate is not None:
                    item.vat_rate = item_update.vat_rate

            item.line_total = quantize_money(item.unit_price * item.quantity)
            subtotal += item.line_total

        order.subtotal = quantize_money(subtotal)

        disc_type_enum = None
        if order.discount_type:
            try:
                disc_type_enum = DiscountType(order.discount_type)
            except ValueError:
                pass

        stored_discount_type, stored_discount_value, discount_amount = calculate_discount(
            order.subtotal,
            disc_type_enum,
            order.discount_value,
        )

        order.discount_amount = discount_amount
        order.final_total = quantize_money(order.subtotal - discount_amount)

        subtotal_float = float(order.subtotal)
        discount_float = float(discount_amount)
        ratio = (subtotal_float - discount_float) / subtotal_float if subtotal_float > 0 else 1.0

        for item in order.items:
            line_gross = float(item.line_total)
            line_net = line_gross * ratio
            item.vat_amount = round(line_net * (item.vat_rate / 100.0), 2)

        order.total_vat = sum(item.vat_amount for item in order.items)

        db.commit()
        db.refresh(order)

        return build_sales_order_detail_response(order)
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin", "salesperson")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin", "salesperson")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    ensure_order_access(order, current_user, db)
    return order


@router.delete(
    "/{order_id}",
    summary="Delete an unsynced order",
    description="Root Admin only. Deletes an order if it has not been synced to Sage 50.",
)
@admin_router.delete(
    "/{order_id}",
    summary="Delete an unsynced order",
    description="Root Admin only. Deletes an order if it has not been synced to Sage 50.",
)
def delete_order(
    order_id: int,
    current_user: User = Depends(require_roles("root_admin")),
    db: Session = Depends(get_db),
):
    if current_user.role != "root_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    if order.sage_sync_status in ("synced", OrderSageSyncStatus.SYNCED.value, "completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete this record because it has already been synced with Sage 50.",
        )

    db.query(OrderItem).filter(OrderItem.order_id == order.id).delete(synchronize_session=False)
    db.delete(order)
    db.commit()

    return {"status": "success", "message": f"Order {order_id} deleted successfully"}


def generate_sales_order_pdf_bytes(order: Order) -> bytes:
    """
    Generates a professional A4 PDF invoice for a Sales Order using ReportLab.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0F172A'),
        alignment=2
    )

    company_title = ParagraphStyle(
        'CompanyTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0D9488')
    )

    normal_text = ParagraphStyle(
        'NormalText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#334155')
    )

    bold_text = ParagraphStyle(
        'BoldText',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#0F172A')
    )

    header_cell = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white
    )

    # 1. Header Block: Left Header uses Official Logo
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_path = os.path.join(base_dir, "assets", "logo.png")

    if os.path.exists(logo_path):
        left_header = [RLImage(logo_path, width=95, height=90)]
    else:
        left_header = [Paragraph("<b>ORBIT FOOD LIMITED</b>", company_title)]

    order_num = order.order_number or f"SO-PEND-{order.id}"
    created_str = order.created_at.strftime("%d/%m/%Y %H:%M") if order.created_at else datetime.now().strftime("%d/%m/%Y %H:%M")
    created_by_role = getattr(order, "created_by_role", "customer") or "customer"
    salesperson_name = "Direct Customer Purchase"
    if created_by_role == "salesperson":
        salesperson_name = "Salesperson Assisted"

    sage_ref = order.sage_order_number or "Not Synced"
    sync_status = (order.sage_sync_status or "pending").capitalize()

    right_header = [
        Paragraph("SALES ORDER", title_style),
        Spacer(1, 4),
        Paragraph(f"<b>Order No:</b> {order_num}", ParagraphStyle('RightText', parent=bold_text, alignment=2)),
        Paragraph(f"<b>Date:</b> {created_str}", ParagraphStyle('RightText', parent=normal_text, alignment=2)),
        Paragraph(f"<b>Created By:</b> {salesperson_name}", ParagraphStyle('RightText', parent=normal_text, alignment=2)),
        Paragraph(f"<b>Sage Ref:</b> {sage_ref} ({sync_status})", ParagraphStyle('RightText', parent=normal_text, alignment=2)),
    ]

    header_table = Table([[left_header, right_header]], colWidths=[200, 322])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))

    story.append(header_table)
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E2E8F0'), spaceBefore=0, spaceAfter=15))

    # 2. Customer & Address Block
    shop = order.shop
    company_name = shop.company_name if shop else "N/A"
    contact_name = (shop.contact_name if shop else "") or "N/A"
    account_ref = (order.account_ref or (shop.account_ref if shop else "")) or "N/A"
    phone = (shop.phone_number if shop else "") or "N/A"
    email = (shop.user.email if shop and shop.user else "") or "N/A"
    address = (f"{shop.address}, {shop.city}, {shop.postcode}" if shop else "N/A")

    cust_box = [
        Paragraph("<b>CUSTOMER DETAILS</b>", bold_text),
        Spacer(1, 4),
        Paragraph(f"<b>Company:</b> {company_name}", normal_text),
        Paragraph(f"<b>Account Ref:</b> {account_ref}", normal_text),
        Paragraph(f"<b>Contact:</b> {contact_name}", normal_text),
        Paragraph(f"<b>Phone:</b> {phone}", normal_text),
        Paragraph(f"<b>Email:</b> {email}", normal_text),
    ]

    address_box = [
        Paragraph("<b>BILLING ADDRESS</b>", bold_text),
        Spacer(1, 4),
        Paragraph("<b>Orbit Food Ltd</b>", normal_text),
        Paragraph("Unit 01 pool street", normal_text),
        Paragraph("WV2 4HN", normal_text),
    ]

    info_table = Table([[cust_box, address_box]], colWidths=[260, 262])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))

    story.append(info_table)
    story.append(Spacer(1, 15))

    # 3. Line Items Table
    table_data = [
        [
            Paragraph("<b>#</b>", header_cell),
            Paragraph("<b>SKU</b>", header_cell),
            Paragraph("<b>Product Name</b>", header_cell),
            Paragraph("<b>Qty</b>", header_cell),
            Paragraph("<b>Unit Price (ex. VAT)</b>", header_cell),
            Paragraph("<b>VAT %</b>", header_cell),
            Paragraph("<b>Total (ex. VAT)</b>", header_cell),
            Paragraph("<b>Total (inc. VAT)</b>", header_cell),
        ]
    ]

    cell_style = ParagraphStyle('Cell', parent=normal_text, fontSize=8, leading=10)
    cell_bold = ParagraphStyle('CellBold', parent=bold_text, fontSize=8, leading=10)

    subtotal_ex_vat = 0.0
    calc_vat_total = 0.0

    for idx, item in enumerate(order.items, start=1):
        p_code = item.product_code or "-"
        p_name = item.product_name or "-"
        qty = item.quantity
        price = float(item.unit_price)

        # 1. Map Dynamic VAT Rate (strictly pull item.vat_rate, do NOT convert 0.0 to 20.0 via falsy 'or')
        raw_vat = getattr(item, "vat_rate", None)
        vat_rate = float(raw_vat) if raw_vat is not None else 20.0

        # 2. Fix Line Item Totals:
        # Formula: (Unit Price * Quantity) * (1 + (Item VAT Rate / 100))
        line_ex = price * qty
        line_vat = line_ex * (vat_rate / 100.0)
        line_inc = line_ex * (1.0 + (vat_rate / 100.0))

        subtotal_ex_vat += line_ex
        calc_vat_total += line_vat

        vat_rate_str = f"{vat_rate:.0f}%" if vat_rate.is_integer() else f"{vat_rate:.1f}%"

        table_data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(p_code, cell_style),
            Paragraph(p_name, cell_style),
            Paragraph(str(qty), cell_style),
            Paragraph(f"£{price:.2f}", cell_style),
            Paragraph(vat_rate_str, cell_style),
            Paragraph(f"£{line_ex:.2f}", cell_style),
            Paragraph(f"£{line_inc:.2f}", cell_bold),
        ])

    # 3. Document Grand Totals (matching UI totals & database exact figures)
    subtotal_val = float(order.subtotal) if order.subtotal is not None else subtotal_ex_vat
    discount_amount = float(order.discount_amount or 0.0)
    net_subtotal = max(0.0, subtotal_val - discount_amount)

    total_vat = float(order.total_vat) if getattr(order, "total_vat", None) is not None else calc_vat_total
    grand_total = net_subtotal + total_vat

    items_table = Table(table_data, colWidths=[20, 75, 165, 30, 65, 42, 60, 65])

    t_style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0D9488')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
    ]

    for r in range(1, len(table_data)):
        if r % 2 == 0:
            t_style.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#F8FAFC')))

    items_table.setStyle(TableStyle(t_style))
    story.append(items_table)
    story.append(Spacer(1, 15))

    # 4. Totals Box
    totals_data = [
        [Paragraph("<b>Subtotal (Excl. VAT):</b>", normal_text), Paragraph(f"£{subtotal_val:.2f}", bold_text)]
    ]

    if discount_amount > 0:
        disc_label = "Discount"
        if order.discount_type == "percentage" and order.discount_value:
            disc_label += f" ({float(order.discount_value):.0f}%)"
        elif order.discount_type == "fixed":
            disc_label += " (Fixed)"

        totals_data.append([
            Paragraph(f"<b>{disc_label}:</b>", normal_text),
            Paragraph(f"-£{discount_amount:.2f}", bold_text)
        ])

    totals_data.extend([
        [Paragraph("<b>Total VAT:</b>", normal_text), Paragraph(f"£{total_vat:.2f}", bold_text)],
        [
            Paragraph("<b>Grand Total (Incl. VAT):</b>", ParagraphStyle('GrandTitle', parent=bold_text, fontSize=10, textColor=colors.HexColor('#0D9488'))),
            Paragraph(f"<b>£{grand_total:.2f}</b>", ParagraphStyle('GrandVal', parent=bold_text, fontSize=10, textColor=colors.HexColor('#0D9488')))
        ]
    ])

    totals_table = Table(totals_data, colWidths=[140, 90])
    totals_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LINEBELOW', (0,0), (-1,-2), 0.5, colors.HexColor('#E2E8F0')),
        ('LINEBELOW', (0,-1), (-1,-1), 1.5, colors.HexColor('#0D9488')),
    ]))

    summary_wrapper = Table([["", totals_table]], colWidths=[292, 230])
    summary_wrapper.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))

    story.append(summary_wrapper)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


@router.get("/{order_id}/pdf")
@router.get("/api/orders/{order_id}/pdf")
@admin_router.get("/{order_id}/pdf")
@admin_router.get("/api/orders/{order_id}/pdf")
def get_order_pdf(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ["root_admin", "admin", "salesperson"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. PDF invoices are restricted to admin and sales personnel.",
        )

    order = None

    # 1. Try querying by integer primary key first
    if order_id.isdigit():
        order = (
            db.query(Order)
            .options(joinedload(Order.shop), joinedload(Order.items))
            .filter(Order.id == int(order_id))
            .first()
        )

    # 2. Fallback to order_number matching (e.g. SO-000003)
    if not order:
        clean_id = order_id.strip()
        order = (
            db.query(Order)
            .options(joinedload(Order.shop), joinedload(Order.items))
            .filter(
                or_(
                    Order.order_number == clean_id,
                    Order.order_number == f"SO-{clean_id}",
                    Order.order_number == f"SO-{clean_id.zfill(6)}"
                )
            )
            .first()
        )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found",
        )

    ensure_order_access(order, current_user, db)

    try:
        pdf_bytes = generate_sales_order_pdf_bytes(order)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF generation library 'reportlab' is missing on the server. Please run pip install reportlab",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF invoice: {str(e)}",
        )

    filename = f"SalesOrder_{order.order_number or order.id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


