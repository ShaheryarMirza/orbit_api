from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
import xml.etree.ElementTree as ET

from app.db.database import get_db
from app.models.order import Order, OrderStatus, OrderSageSyncStatus
from app.api.zynk_xml_utils import generate_zynk_sales_order_xml
import os

router = APIRouter(tags=["Sage Sync"])

def verify_zynk_token(authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    val = authorization.strip()
    if val == "Bearer admin123" or val == "admin123":
        return val
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )

@router.get("/api/sage/orders/pending")
def get_pending_orders_for_zynk(
    db: Session = Depends(get_db),
    token: str = Depends(verify_zynk_token)
):
    orders = (
        db.query(Order)
        .options(joinedload(Order.shop), joinedload(Order.items))
        .filter(Order.status == OrderStatus.PLACED.value)
        .filter(Order.sage_sync_status != OrderSageSyncStatus.SYNCED.value)
        .all()
    )

    xml_data = generate_zynk_sales_order_xml(orders)

    return Response(content=xml_data, media_type="application/xml")

@router.post("/api/sage/orders/status")
async def update_sage_order_statuses(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(verify_zynk_token)
):
    body = await request.body()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="Invalid XML payload")

    for sales_order in root.iter("SalesOrder"):
        order_id_node = sales_order.find("Id")
        if order_id_node is None or not order_id_node.text:
            continue
        
        try:
            order_id = int(order_id_node.text)
        except ValueError:
            continue
            
        sales_order_number_node = sales_order.find("SalesOrderNumber")
        account_reference_node = sales_order.find("AccountReference")
        
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            order.sage_sync_status = OrderSageSyncStatus.SYNCED.value
            
            if sales_order_number_node is not None and sales_order_number_node.text:
                order.sage_order_number = sales_order_number_node.text
                
            if account_reference_node is not None and account_reference_node.text:
                order.account_ref = account_reference_node.text
                if order.shop:
                    order.shop.account_ref = account_reference_node.text
                
    db.commit()
    
    return {"status": "success", "message": "Sync statuses updated"}

@router.post("/api/sage/orders/fail")
async def record_sage_order_failures(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(verify_zynk_token)
):
    body = await request.body()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="Invalid XML payload")

    # Look for elements representing failed items (usually <SalesOrder> or tags with an <Id>)
    failed_items = list(root.iter("SalesOrder"))
    if not failed_items:
        # Fallback: scan all elements that contain a child <Id> node
        failed_items = [el for el in root.iter() if el.find("Id") is not None]

    for item in failed_items:
        id_node = item.find("Id")
        if id_node is None or not id_node.text:
            continue
        
        try:
            order_id = int(id_node.text)
        except ValueError:
            continue

        # Extract failure explanation
        error_msg = ""
        msg_node = item.find("Message")
        err_node = item.find("Error")
        
        if msg_node is not None and msg_node.text:
            error_msg = msg_node.text.strip()
        elif err_node is not None and err_node.text:
            error_msg = err_node.text.strip()
        else:
            error_msg = "Sync failed during Zynk Workflow execution."

        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            order.sage_sync_status = OrderSageSyncStatus.FAILED.value
            order.sync_notes = error_msg

    db.commit()
    return {"status": "recorded", "message": "Failure notes captured"}


@router.get("/api/sage/test-connection")
def test_sage_connection(
    token: str = Depends(verify_zynk_token)
):
    return {"status": "success", "message": "Zynk is successfully authenticated with the backend!"}
