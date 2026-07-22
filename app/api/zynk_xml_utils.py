from typing import List
import xml.etree.ElementTree as ET
from datetime import datetime

from app.models.order import Order

def generate_zynk_sales_order_xml(orders: List[Order]) -> str:
    """
    Takes a list of un-synced orders and generates an XML string
    formatted to the Zynk Sage 50 UK Sales Order XML schema,
    including customer details to support Auto Create Account.
    """
    company = ET.Element(
        "Company",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
        }
    )
    sales_orders = ET.SubElement(company, "SalesOrders")

    for order in orders:
        sales_order = ET.SubElement(sales_orders, "SalesOrder")
        
        # 1. Internal order ID mapped to Id
        order_id_node = ET.SubElement(sales_order, "Id")
        order_id_node.text = str(order.id)

        # 2. AccountReference mapped from the order (with fallback to shop)
        account_reference = ET.SubElement(sales_order, "AccountReference")
        account_ref_val = getattr(order, "account_ref", None) or getattr(order, "sage_account_reference", None) or ""
        if not account_ref_val and order.shop:
            account_ref_val = (
                getattr(order.shop, "account_ref", None)
                or getattr(order.shop, "sage_account_reference", None)
                or getattr(order.shop, "sage_account_ref", None)
                or ""
            )
        account_reference.text = str(account_ref_val)

        # 2b. Customer node (to support Auto Create Account in Sage 50 via Zynk)
        if order.shop:
            customer_node = ET.SubElement(sales_order, "Customer")
            
            unique_id_node = ET.SubElement(customer_node, "UniqueId")
            unique_id_node.text = str(account_ref_val)
            
            cust_account_ref = ET.SubElement(customer_node, "AccountReference")
            cust_account_ref.text = str(account_ref_val)
            
            company_name_node = ET.SubElement(customer_node, "CompanyName")
            company_name_node.text = order.shop.company_name
            
            if getattr(order.shop, "company_registration_number", None):
                vat_node = ET.SubElement(customer_node, "VatNumber")
                vat_node.text = order.shop.company_registration_number

            # CustomerInvoiceAddress
            invoice_address = ET.SubElement(customer_node, "CustomerInvoiceAddress")
            inv_addr1 = ET.SubElement(invoice_address, "Address1")
            inv_addr1.text = order.shop.address
            if getattr(order.shop, "address_line_2", None):
                inv_addr2 = ET.SubElement(invoice_address, "Address2")
                inv_addr2.text = order.shop.address_line_2
            inv_town = ET.SubElement(invoice_address, "Town")
            inv_town.text = order.shop.city
            inv_postcode = ET.SubElement(invoice_address, "Postcode")
            inv_postcode.text = order.shop.postcode
            inv_country = ET.SubElement(invoice_address, "Country")
            inv_country.text = getattr(order.shop, "country", "GB")
            inv_tel = ET.SubElement(invoice_address, "Telephone")
            inv_tel.text = order.shop.phone_number
            if getattr(order.shop, "fax", None):
                inv_fax = ET.SubElement(invoice_address, "Fax")
                inv_fax.text = order.shop.fax
            if getattr(order.shop, "website", None):
                inv_web = ET.SubElement(invoice_address, "Website")
                inv_web.text = order.shop.website
            if order.shop.user and getattr(order.shop.user, "email", None):
                inv_email = ET.SubElement(invoice_address, "Email")
                inv_email.text = order.shop.user.email

            # CustomerDeliveryAddress
            delivery_address = ET.SubElement(customer_node, "CustomerDeliveryAddress")
            del_addr1 = ET.SubElement(delivery_address, "Address1")
            del_addr1.text = order.shop.address
            if getattr(order.shop, "address_line_2", None):
                del_addr2 = ET.SubElement(delivery_address, "Address2")
                del_addr2.text = order.shop.address_line_2
            del_town = ET.SubElement(delivery_address, "Town")
            del_town.text = order.shop.city
            del_postcode = ET.SubElement(delivery_address, "Postcode")
            del_postcode.text = order.shop.postcode
            del_country = ET.SubElement(delivery_address, "Country")
            del_country.text = getattr(order.shop, "country", "GB")
            del_tel = ET.SubElement(delivery_address, "Telephone")
            del_tel.text = order.shop.phone_number
            if getattr(order.shop, "fax", None):
                del_fax = ET.SubElement(delivery_address, "Fax")
                del_fax.text = order.shop.fax
            if order.shop.user and getattr(order.shop.user, "email", None):
                del_email = ET.SubElement(delivery_address, "Email")
                del_email.text = order.shop.user.email

        # 3. SalesOrderDate mapped from created_at
        sales_order_date = ET.SubElement(sales_order, "SalesOrderDate")
        if order.created_at:
            sales_order_date.text = order.created_at.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            sales_order_date.text = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        # 4. SalesOrderAddress
        if order.shop:
            sales_order_address = ET.SubElement(sales_order, "SalesOrderAddress")
            company_node = ET.SubElement(sales_order_address, "Company")
            company_node.text = order.shop.company_name
            address_node = ET.SubElement(sales_order_address, "Address1")
            address_node.text = order.shop.address
            if getattr(order.shop, "address_line_2", None):
                address2_node = ET.SubElement(sales_order_address, "Address2")
                address2_node.text = order.shop.address_line_2
            town_node = ET.SubElement(sales_order_address, "Town")
            town_node.text = order.shop.city
            postcode_node = ET.SubElement(sales_order_address, "Postcode")
            postcode_node.text = order.shop.postcode
            country_node = ET.SubElement(sales_order_address, "Country")
            country_node.text = getattr(order.shop, "country", "GB")
            tel_node = ET.SubElement(sales_order_address, "Telephone")
            tel_node.text = order.shop.phone_number
            if getattr(order.shop, "fax", None):
                fax_node = ET.SubElement(sales_order_address, "Fax")
                fax_node.text = order.shop.fax
            if getattr(order.shop, "website", None):
                web_node = ET.SubElement(sales_order_address, "Website")
                web_node.text = order.shop.website

            # 5. SalesOrderDeliveryAddress
            sales_order_del_address = ET.SubElement(sales_order, "SalesOrderDeliveryAddress")
            company_del = ET.SubElement(sales_order_del_address, "Company")
            company_del.text = order.shop.company_name
            address_del = ET.SubElement(sales_order_del_address, "Address1")
            address_del.text = order.shop.address
            if getattr(order.shop, "address_line_2", None):
                address2_del = ET.SubElement(sales_order_del_address, "Address2")
                address2_del.text = order.shop.address_line_2
            town_del = ET.SubElement(sales_order_del_address, "Town")
            town_del.text = order.shop.city
            postcode_del = ET.SubElement(sales_order_del_address, "Postcode")
            postcode_del.text = order.shop.postcode
            country_del = ET.SubElement(sales_order_del_address, "Country")
            country_del.text = getattr(order.shop, "country", "GB")
            tel_del = ET.SubElement(sales_order_del_address, "Telephone")
            tel_del.text = order.shop.phone_number
            if getattr(order.shop, "fax", None):
                fax_del = ET.SubElement(sales_order_del_address, "Fax")
                fax_del.text = order.shop.fax

        # 6. Items mapping
        sales_order_items = ET.SubElement(sales_order, "SalesOrderItems")
        
        for item in order.items:
            item_node = ET.SubElement(sales_order_items, "Item")
            
            sku = ET.SubElement(item_node, "Sku")
            sku.text = str(item.product_code)
            
            qty_ordered = ET.SubElement(item_node, "QtyOrdered")
            qty_ordered.text = str(item.quantity)
            
            unit_price = ET.SubElement(item_node, "UnitPrice")
            unit_price.text = str(item.unit_price)

            tax_rate = ET.SubElement(item_node, "TaxRate")
            tax_rate.text = str(getattr(item, "vat_rate", 20.0))

    # Return safely as a decoded UTF-8 string
    return ET.tostring(company, encoding="utf-8").decode("utf-8")


def generate_zynk_customer_xml(shops: List) -> str:
    """
    Takes a list of shops that need syncing and generates a Zynk-compliant
    Customer XML payload with updated details, addresses, and telephone fields.
    """
    company = ET.Element(
        "Company",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
        }
    )
    customers = ET.SubElement(company, "Customers")

    for shop in shops:
        customer = ET.SubElement(customers, "Customer")
        
        unique_id = ET.SubElement(customer, "UniqueId")
        unique_id.text = str(shop.account_ref)
        
        account_ref = ET.SubElement(customer, "AccountReference")
        account_ref.text = str(shop.account_ref)
        
        company_name = ET.SubElement(customer, "CompanyName")
        company_name.text = str(shop.company_name)

        if shop.contact_name:
            contact_name = ET.SubElement(customer, "ContactName")
            contact_name.text = str(shop.contact_name)

        # CustomerInvoiceAddress
        invoice_address = ET.SubElement(customer, "CustomerInvoiceAddress")
        inv_addr1 = ET.SubElement(invoice_address, "Address1")
        inv_addr1.text = str(shop.address)
        if shop.address_line_2:
            inv_addr2 = ET.SubElement(invoice_address, "Address2")
            inv_addr2.text = str(shop.address_line_2)
        inv_town = ET.SubElement(invoice_address, "Town")
        inv_town.text = str(shop.city)
        inv_postcode = ET.SubElement(invoice_address, "Postcode")
        inv_postcode.text = str(shop.postcode)
        inv_country = ET.SubElement(invoice_address, "Country")
        inv_country.text = str(shop.country)
        inv_tel = ET.SubElement(invoice_address, "Telephone")
        inv_tel.text = str(shop.phone_number)
        if shop.telephone_2:
            inv_tel2 = ET.SubElement(invoice_address, "Telephone2")
            inv_tel2.text = str(shop.telephone_2)
        if shop.telephone_3:
            inv_tel3 = ET.SubElement(invoice_address, "Telephone3")
            inv_tel3.text = str(shop.telephone_3)
        if shop.user and shop.user.email:
            inv_email = ET.SubElement(invoice_address, "Email")
            inv_email.text = str(shop.user.email)
        if shop.contact_name:
            inv_contact = ET.SubElement(invoice_address, "ContactName")
            inv_contact.text = str(shop.contact_name)

        # CustomerDeliveryAddress
        delivery_address = ET.SubElement(customer, "CustomerDeliveryAddress")
        del_addr1 = ET.SubElement(delivery_address, "Address1")
        del_addr1.text = str(shop.address)
        if shop.address_line_2:
            del_addr2 = ET.SubElement(delivery_address, "Address2")
            del_addr2.text = str(shop.address_line_2)
        del_town = ET.SubElement(delivery_address, "Town")
        del_town.text = str(shop.city)
        del_postcode = ET.SubElement(delivery_address, "Postcode")
        del_postcode.text = str(shop.postcode)
        del_country = ET.SubElement(delivery_address, "Country")
        del_country.text = str(shop.country)
        del_tel = ET.SubElement(delivery_address, "Telephone")
        del_tel.text = str(shop.phone_number)
        if shop.telephone_2:
            del_tel2 = ET.SubElement(delivery_address, "Telephone2")
            del_tel2.text = str(shop.telephone_2)
        if shop.telephone_3:
            del_tel3 = ET.SubElement(delivery_address, "Telephone3")
            del_tel3.text = str(shop.telephone_3)
        if shop.user and shop.user.email:
            del_email = ET.SubElement(delivery_address, "Email")
            del_email.text = str(shop.user.email)
        if shop.contact_name:
            del_contact = ET.SubElement(delivery_address, "ContactName")
            del_contact.text = str(shop.contact_name)

    return ET.tostring(company, encoding="utf-8").decode("utf-8")


def generate_zynk_product_xml(products: List) -> str:
    """
    Takes a list of products needing Sage sync and generates an XML string
    formatted to Zynk Sage 50 Product XML schema.
    Maps pending_delete status to flag Sage product as Inactive (PublishStatus=Inactive).
    """
    company = ET.Element(
        "Company",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
        }
    )
    products_node = ET.SubElement(company, "Products")

    for prod in products:
        product_node = ET.SubElement(products_node, "Product")
        
        id_node = ET.SubElement(product_node, "Id")
        id_node.text = str(prod.id)

        sku_node = ET.SubElement(product_node, "Sku")
        sku_node.text = str(prod.product_code)

        name_node = ET.SubElement(product_node, "Name")
        name_node.text = str(prod.product_name)

        if prod.description:
            desc_node = ET.SubElement(product_node, "Description")
            desc_node.text = str(prod.description)

        unit_price_node = ET.SubElement(product_node, "UnitPrice")
        unit_price_node.text = str(prod.price)

        tax_rate_node = ET.SubElement(product_node, "TaxRate")
        tax_rate_node.text = str(getattr(prod, "vat_rate", 20.0))

        publish_status_node = ET.SubElement(product_node, "PublishStatus")
        if prod.sage_sync_status == "pending_delete" or not prod.is_active:
            publish_status_node.text = "Inactive"
        else:
            publish_status_node.text = "Active"

        sync_status_node = ET.SubElement(product_node, "SyncStatus")
        sync_status_node.text = str(prod.sage_sync_status)

    return ET.tostring(company, encoding="utf-8").decode("utf-8")
