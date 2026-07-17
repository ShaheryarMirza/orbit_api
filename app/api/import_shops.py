import io
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
import pandas as pd

from app.api.dependencies import require_roles
from app.db.database import get_db
from app.models.user import User
from app.models.shop import Shop, ShopApprovalStatus, SageSyncStatus
from app.utils.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin-import"])


def find_column(df: pd.DataFrame, possible_names: list[str]) -> str | None:
    for col in df.columns:
        if str(col).strip().lower() in possible_names:
            return col
    return None


@router.post(
    "/import-shops",
    status_code=status.HTTP_200_OK,
    summary="Bulk import Sage 50 customers from Excel/CSV",
    description="Allows administrators to upload a customer spreadsheet to batch create shop owners and shops."
)
def import_shops(
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    # Verify file extension
    filename = file.filename or ""
    is_csv = filename.endswith(".csv")
    is_excel = filename.endswith(".xlsx") or filename.endswith(".xls")

    if not (is_csv or is_excel):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only Excel (.xlsx, .xls) and CSV (.csv) files are supported."
        )

    try:
        contents = file.file.read()
        if is_csv:
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse spreadsheet file: {str(exc)}"
        )

    # Clean columns: strip whitespace
    df.columns = [str(c).strip() for c in df.columns]

    # Map possible column names
    col_ref = find_column(df, ["account reference", "accountreference", "account_ref", "account ref", "customer id", "customer_id", "ref", "uniqueid", "unique id"])
    col_name = find_column(df, ["company name", "companyname", "company_name", "name", "customer name", "customer_name"])
    col_email = find_column(df, ["email", "email address", "emailaddress", "contact email", "contact_email"])
    col_phone = find_column(df, ["phone", "phone number", "phone_number", "telephone", "tel", "tel number"])
    col_contact = find_column(df, ["contact name", "contactname", "contact_name", "contact", "primary contact", "primary_contact"])
    col_tel2 = find_column(df, ["telephone 2", "telephone2", "phone 2", "phone_2", "tel 2", "tel_2", "telephone_2"])
    col_tel3 = find_column(df, ["telephone 3", "telephone3", "phone 3", "phone_3", "tel 3", "tel_3", "telephone_3"])
    col_address1 = find_column(df, ["address 1", "address1", "address_line_1", "address line 1", "address"])
    col_address2 = find_column(df, ["address 2", "address2", "address_line_2", "address line 2"])
    col_town = find_column(df, ["town", "city", "town/city", "city/town"])
    col_postcode = find_column(df, ["postcode", "post code", "zip", "zipcode", "zip code"])
    col_country = find_column(df, ["country", "country code", "country_code"])
    col_fax = find_column(df, ["fax", "fax number", "fax_number"])
    col_website = find_column(df, ["website", "web", "url"])
    col_reg = find_column(df, ["company registration number", "company registration", "company_registration_number", "vat number", "vatnumber", "vat_number", "company_reg_no"])

    # Basic check for essential columns
    if not col_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet must contain an 'Email' or 'Email Address' column."
        )
    if not col_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet must contain a 'Company Name' or 'CompanyName' column."
        )

    imported_count = 0
    updated_count = 0
    failed_count = 0
    errors = []

    # Temporary default password
    temp_password = "Orbit@123"
    hashed_temp_pw = hash_password(temp_password)

    processed_emails = set()
    processed_refs = set()

    for index, row in df.iterrows():
        try:
            email_val = str(row[col_email]).strip().lower() if col_email and pd.notna(row[col_email]) else ""
            if not email_val or "@" not in email_val:
                failed_count += 1
                errors.append(f"Row {index + 2}: Missing or invalid email address.")
                continue

            company_name_val = str(row[col_name]).strip() if col_name and pd.notna(row[col_name]) else ""
            if not company_name_val:
                failed_count += 1
                errors.append(f"Row {index + 2}: Missing company name.")
                continue

            # Optional / default columns
            ref_val = str(row[col_ref]).strip().upper() if col_ref and pd.notna(row[col_ref]) else ""
            phone_val = str(row[col_phone]).strip() if col_phone and pd.notna(row[col_phone]) else "0"
            contact_val = str(row[col_contact]).strip() if col_contact and pd.notna(row[col_contact]) else None
            tel2_val = str(row[col_tel2]).strip() if col_tel2 and pd.notna(row[col_tel2]) else None
            tel3_val = str(row[col_tel3]).strip() if col_tel3 and pd.notna(row[col_tel3]) else None
            address1_val = str(row[col_address1]).strip() if col_address1 and pd.notna(row[col_address1]) else "Unknown"
            address2_val = str(row[col_address2]).strip() if col_address2 and pd.notna(row[col_address2]) else None
            town_val = str(row[col_town]).strip() if col_town and pd.notna(row[col_town]) else "Unknown"
            postcode_val = str(row[col_postcode]).strip() if col_postcode and pd.notna(row[col_postcode]) else "Unknown"
            country_val = str(row[col_country]).strip() if col_country and pd.notna(row[col_country]) else "GB"
            fax_val = str(row[col_fax]).strip() if col_fax and pd.notna(row[col_fax]) else None
            website_val = str(row[col_website]).strip() if col_website and pd.notna(row[col_website]) else None
            reg_val = str(row[col_reg]).strip() if col_reg and pd.notna(row[col_reg]) else None

            # 1. Uniqueness check in current batch (in-memory)
            if email_val in processed_emails:
                failed_count += 1
                errors.append(f"Row {index + 2}: Duplicate email '{email_val}' in this spreadsheet.")
                continue
            if ref_val and ref_val in processed_refs:
                failed_count += 1
                errors.append(f"Row {index + 2}: Duplicate account reference '{ref_val}' in this spreadsheet.")
                continue

            processed_emails.add(email_val)
            if ref_val:
                processed_refs.add(ref_val)

            # 2. Run row within nested transaction savepoint to isolate database conflicts
            with db.begin_nested():
                # Generate OR1xxx ref code if unassigned
                if not ref_val:
                    all_refs = db.query(Shop.account_ref).filter(Shop.account_ref.like("OR1%")).all()
                    max_num = 1000
                    for ref_tuple in all_refs:
                        ref = ref_tuple[0]
                        if ref:
                            import re
                            match = re.match(r"^OR1(\d+)$", ref)
                            if match:
                                val = int(match.group(1))
                                if val > max_num:
                                    max_num = val
                    ref_val = f"OR1{max_num + 1}"
                    processed_refs.add(ref_val)

                # Check if user already exists
                user = db.query(User).filter(User.email == email_val).first()
                if user:
                    # Update existing user role/permissions to shop_owner
                    user.role = "shop_owner"
                    user.must_change_password = False
                    if contact_val:
                        user.name = contact_val
                    
                    # Check for shop
                    shop = db.query(Shop).filter(Shop.user_id == user.id).first()
                    if shop:
                        # Check unique constraint if account_ref changes
                        if ref_val != shop.account_ref:
                            exist = db.query(Shop).filter(Shop.account_ref == ref_val).first()
                            if exist:
                                raise ValueError(f"Account reference '{ref_val}' is already assigned to another B2B shop.")
                        
                        shop.company_name = company_name_val
                        shop.contact_name = contact_val or shop.contact_name or company_name_val
                        shop.phone_number = phone_val
                        shop.telephone_2 = tel2_val or shop.telephone_2
                        shop.telephone_3 = tel3_val or shop.telephone_3
                        shop.address = address1_val
                        shop.address_line_2 = address2_val
                        shop.postcode = postcode_val
                        shop.city = town_val
                        shop.country = country_val
                        shop.fax = fax_val
                        shop.website = website_val
                        shop.company_registration_number = reg_val or shop.company_registration_number
                        shop.account_ref = ref_val
                        shop.approval_status = ShopApprovalStatus.APPROVED.value
                        shop.sage_sync_status = SageSyncStatus.SYNCED.value
                    else:
                        # Check unique constraint
                        exist = db.query(Shop).filter(Shop.account_ref == ref_val).first()
                        if exist:
                            raise ValueError(f"Account reference '{ref_val}' is already assigned to another B2B shop.")
                            
                        shop = Shop(
                            user_id=user.id,
                            company_name=company_name_val,
                            contact_name=contact_val or company_name_val,
                            phone_number=phone_val,
                            telephone_2=tel2_val,
                            telephone_3=tel3_val,
                            address=address1_val,
                            address_line_2=address2_val,
                            postcode=postcode_val,
                            city=town_val,
                            country=country_val,
                            fax=fax_val,
                            website=website_val,
                            company_registration_number=reg_val,
                            account_ref=ref_val,
                            approval_status=ShopApprovalStatus.APPROVED.value,
                            sage_sync_status=SageSyncStatus.SYNCED.value,
                        )
                        db.add(shop)
                    updated_count += 1
                else:
                    # Check unique constraint
                    exist = db.query(Shop).filter(Shop.account_ref == ref_val).first()
                    if exist:
                        raise ValueError(f"Account reference '{ref_val}' is already assigned to another B2B shop.")

                    # Create User
                    user = User(
                        name=contact_val or company_name_val,
                        email=email_val,
                        password_hash=hashed_temp_pw,
                        role="shop_owner",
                        is_active=True,
                        must_change_password=False,
                    )
                    db.add(user)
                    db.flush()

                    # Create Shop
                    shop = Shop(
                        user_id=user.id,
                        company_name=company_name_val,
                        contact_name=contact_val or company_name_val,
                        phone_number=phone_val,
                        telephone_2=tel2_val,
                        telephone_3=tel3_val,
                        address=address1_val,
                        address_line_2=address2_val,
                        postcode=postcode_val,
                        city=town_val,
                        country=country_val,
                        fax=fax_val,
                        website=website_val,
                        company_registration_number=reg_val,
                        account_ref=ref_val,
                        approval_status=ShopApprovalStatus.APPROVED.value,
                        sage_sync_status=SageSyncStatus.SYNCED.value,
                    )
                    db.add(shop)
                    imported_count += 1
                
                db.flush() # Force SQL generation to catch unique constraints early

        except Exception as exc:
            failed_count += 1
            # Extract readable DB error detail
            detail = str(exc)
            if "duplicate key value violates unique constraint" in detail:
                if "account_ref" in detail or "shops_account_ref_key" in detail:
                    detail = f"Account reference '{ref_val}' is already used by another shop."
                elif "email" in detail or "users_email_key" in detail:
                    detail = f"Email address '{email_val}' is already used by another user."
            errors.append(f"Row {index + 2}: Exception during import - {detail}")

    db.commit()

    return {
        "status": "success",
        "imported": imported_count,
        "updated": updated_count,
        "failed": failed_count,
        "errors": errors,
    }
