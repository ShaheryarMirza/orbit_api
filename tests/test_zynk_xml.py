import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal

from app.api.zynk_xml_utils import generate_zynk_sales_order_xml


class DummyShop:
    def __init__(self):
        self.account_ref = "CUST001"
        self.company_name = "Acme Widgets Ltd"
        self.company_registration_number = "GB123456789"
        self.address = "123 High Street"
        self.address_line_2 = "Suite 4"
        self.city = "London"
        self.postcode = "EC1A 1BB"
        self.country = "GB"
        self.phone_number = "02079460000"
        self.fax = None
        self.website = "https://acme.example.com"
        self.contact_name = "John Doe"
        self.user = None


class DummyOrderItem:
    def __init__(self, product_code, product_name, unit_price, quantity, vat_rate=20.0, vat_amount=0.0):
        self.product_code = product_code
        self.product_name = product_name
        self.unit_price = Decimal(str(unit_price))
        self.quantity = quantity
        self.vat_rate = vat_rate
        self.vat_amount = vat_amount


class DummyOrder:
    def __init__(self, order_id, items, discount_type=None, discount_value=0, discount_amount=0, subtotal=100.0, final_total=100.0, total_vat=20.0):
        self.id = order_id
        self.shop = DummyShop()
        self.account_ref = "CUST001"
        self.created_at = datetime(2026, 9, 7, 12, 0, 0)
        self.items = items
        self.discount_type = discount_type
        self.discount_value = Decimal(str(discount_value)) if discount_value else None
        self.discount_amount = Decimal(str(discount_amount))
        self.subtotal = Decimal(str(subtotal))
        self.final_total = Decimal(str(final_total))
        self.total_vat = total_vat


def test_generate_zynk_sales_order_xml_no_discount():
    items = [
        DummyOrderItem("PROD01", "Widget A", 50.00, 2, vat_rate=20.0, vat_amount=20.0)
    ]
    order = DummyOrder(
        order_id=101,
        items=items,
        discount_type=None,
        discount_value=0,
        discount_amount=0,
        subtotal=100.00,
        final_total=100.00,
        total_vat=20.00
    )

    xml_str = generate_zynk_sales_order_xml([order])
    root = ET.fromstring(xml_str)

    sales_order = root.find("SalesOrders/SalesOrder")
    assert sales_order is not None

    # Header discount tags
    assert sales_order.find("DiscountPercent").text == "0.00"
    assert sales_order.find("DiscountAmount").text == "0.00"
    assert sales_order.find("NetValueDiscountPercent").text == "0.00"
    assert sales_order.find("NetValueDiscount").text == "0.00"

    # Header totals
    assert sales_order.find("NetTotal").text == "100.00"
    assert sales_order.find("TaxTotal").text == "20.00"
    assert sales_order.find("GrossTotal").text == "120.00"

    # Bypass flags
    assert sales_order.find("OverRideCustomerDiscounts").text == "true"
    assert sales_order.find("OverrideCustomerDiscounts").text == "true"
    assert sales_order.find("BypassCustomerDiscounts").text == "true"

    # Line item tags
    item = sales_order.find("SalesOrderItems/Item")
    assert item is not None
    assert item.find("UnitPrice").text == "50.00"
    assert item.find("DiscountPercent").text == "0.00"
    assert item.find("DiscountAmount").text == "0.00"
    assert item.find("UnitDiscountPercentage").text == "0.00"
    assert item.find("UnitDiscountAmount").text == "0.00"


def test_generate_zynk_sales_order_xml_with_discount():
    # User example SO-000248 / SO-000241 with discounted line VAT:
    # Item 1: 2 x £6.72 = £13.44 (0% VAT = £0.00 VAT)
    # Item 2: 4 x £5.00 = £20.00 -> Net after 10% disc = £18.00 (20% VAT = £3.60 VAT)
    # Subtotal: £33.44, Discount (10%): £3.34, Final Net Total: £30.10, Total VAT: £3.60, Gross Total: £33.70
    items = [
        DummyOrderItem("00035-03", "Ulker Baby Biscuit 12x172g", 6.72, 2, vat_rate=0.0, vat_amount=0.0),
        DummyOrderItem("8074", "Tazech Orange TP 36x200ML", 5.00, 4, vat_rate=20.0, vat_amount=3.60),
    ]
    order = DummyOrder(
        order_id=248,
        items=items,
        discount_type="percentage",
        discount_value=10.00,
        discount_amount=3.34,
        subtotal=33.44,
        final_total=30.10,
        total_vat=3.60
    )

    xml_str = generate_zynk_sales_order_xml([order])
    root = ET.fromstring(xml_str)

    sales_order = root.find("SalesOrders/SalesOrder")
    assert sales_order is not None

    # Header discount tags passed as order-level header discount
    assert sales_order.find("DiscountPercent").text == "10.00"
    assert sales_order.find("DiscountAmount").text == "3.34"
    assert sales_order.find("NetValueDiscountPercent").text == "10.00"
    assert sales_order.find("NetValueDiscount").text == "3.34"
    assert sales_order.find("NetValueDiscountDescription").text == "Order Discount (10%)"

    # Header totals must match exact portal values (£30.10 net, £3.60 VAT, £33.70 gross)
    assert sales_order.find("NetTotal").text == "30.10"
    assert sales_order.find("TaxTotal").text == "3.60"
    assert sales_order.find("GrossTotal").text == "33.70"

    # Line items: 2 normal items with full catalog prices and 0.00 line discounts
    xml_items = sales_order.findall("SalesOrderItems/Item")
    assert len(xml_items) == 2

    # Line 1: Item 1
    assert xml_items[0].find("Sku").text == "00035-03"
    assert xml_items[0].find("UnitPrice").text == "6.72"
    assert xml_items[0].find("UnitDiscountPercentage").text == "0.00"
    assert xml_items[0].find("UnitDiscountAmount").text == "0.00"
    assert xml_items[0].find("TaxAmount").text == "0.00"
    assert xml_items[0].find("TaxCode").text == "0"

    # Line 2: Item 2
    assert xml_items[1].find("Sku").text == "8074"
    assert xml_items[1].find("UnitPrice").text == "5.00"
    assert xml_items[1].find("UnitDiscountPercentage").text == "0.00"
    assert xml_items[1].find("UnitDiscountAmount").text == "0.00"
    assert xml_items[1].find("TaxAmount").text == "3.60"
    assert xml_items[1].find("TaxCode").text == "1"
