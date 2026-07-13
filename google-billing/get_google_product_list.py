import sys
import json
import requests
from google.oauth2 import service_account
import google.auth.transport.requests

# --- CONFIGURATION ---
# 1. Update this to match your real Android package name
PACKAGE_NAME = "com.kinshield"

# 2. Update this to match your Service Account JSON filename
SERVICE_ACCOUNT_FILE = "/Users/khangtran/Desktop/kinshield/kinshield-prod-3553bd2e19f2.json"

# The mandatory OAuth scope for accessing Google Play Console data
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]
BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"
PAGE_SIZE = 1000
OUTPUT_FILE = "google_product_catalog.json"
# Set to [] to print every region returned by Google Play.
PRICE_REGIONS = ["VN", "US"]


def get_credentials(json_path, scopes):
    """Loads service-account credentials and generates a short-lived OAuth token."""
    try:
        creds = service_account.Credentials.from_service_account_file(
            json_path, scopes=scopes
        )
        # Force a refresh to generate the raw token string
        auth_request = google.auth.transport.requests.Request()
        creds.refresh(auth_request)
        return creds
    except Exception as e:
        print(f"❌ Error authenticating with Service Account: {e}")
        sys.exit(1)


def get_json(response):
    try:
        return response.json()
    except ValueError:
        return {"raw_response": response.text}


def list_paginated_resource(resource_name, url, headers, response_key):
    items = []
    page_token = None

    while True:
        params = {"pageSize": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        print(f"🔗 URL: {url}")
        response = requests.get(url, headers=headers, params=params, timeout=30)
        payload = get_json(response)

        if response.status_code != 200:
            print(f"❌ {resource_name} request failed (Status Code: {response.status_code})")
            print(json.dumps(payload, indent=4, ensure_ascii=False))
            return None

        page_items = payload.get(response_key, [])
        items.extend(page_items)
        page_token = payload.get("nextPageToken")

        if not page_token:
            return items


def list_token_paginated_resource(resource_name, url, headers, response_key):
    items = []
    page_token = None

    while True:
        params = {}
        if page_token:
            params["token"] = page_token

        print(f"🔗 URL: {url}")
        response = requests.get(url, headers=headers, params=params, timeout=30)
        payload = get_json(response)

        if response.status_code != 200:
            print(f"❌ {resource_name} request failed (Status Code: {response.status_code})")
            print(json.dumps(payload, indent=4, ensure_ascii=False))
            return None

        page_items = payload.get(response_key, [])
        items.extend(page_items)
        page_token = payload.get("tokenPagination", {}).get("nextPageToken")

        if not page_token:
            return items


def format_money(price):
    if not price:
        return "N/A"

    units = int(price.get("units", 0))
    nanos = int(price.get("nanos", 0))
    amount = units + nanos / 1_000_000_000
    return f"{price.get('currencyCode', '')} {amount:.2f}".strip()


def title_from_listings(product):
    listings = product.get("listings", [])
    if not listings:
        return "Untitled"

    english_listing = next(
        (listing for listing in listings if listing.get("languageCode") == "en-US"),
        listings[0],
    )
    return english_listing.get("title", "Untitled")


def format_regional_prices(configs, availability_key="availability"):
    prices = []
    for config in configs:
        region_code = config.get("regionCode", "Other")
        if PRICE_REGIONS and region_code not in PRICE_REGIONS:
            continue

        availability = config.get(availability_key)
        if isinstance(availability, bool):
            suffix = " (available)" if availability else " (unavailable)"
        else:
            suffix = f" ({availability})" if availability else ""
        prices.append(f"{region_code}: {format_money(config.get('price'))}{suffix}")

    if PRICE_REGIONS and not prices:
        prices.append(f"No prices found for regions: {', '.join(PRICE_REGIONS)}")

    return prices


def print_one_time_products(products):
    print("\nOne-time products")
    if not products:
        print("- None")
        return

    for product in products:
        print(f"- {product.get('productId')} | {title_from_listings(product)}")

        for option in product.get("purchaseOptions", []):
            print(
                f"  Purchase option: {option.get('purchaseOptionId')} "
                f"| state: {option.get('state', 'UNKNOWN')}"
            )

            prices = format_regional_prices(
                option.get("regionalPricingAndAvailabilityConfigs", [])
            )
            for price in prices:
                print(f"    {price}")


def print_subscriptions(subscriptions):
    print("\nSubscriptions")
    if not subscriptions:
        print("- None")
        return

    for subscription in subscriptions:
        product_id = subscription.get("productId")
        print(f"- {product_id} | {title_from_listings(subscription)}")

        for base_plan in subscription.get("basePlans", []):
            plan_type = base_plan.get("autoRenewingBasePlanType", {})
            billing_period = plan_type.get("billingPeriodDuration", "N/A")
            print(
                f"  Base plan: {base_plan.get('basePlanId')} "
                f"| state: {base_plan.get('state', 'UNKNOWN')} "
                f"| billing period: {billing_period}"
            )

            prices = format_regional_prices(
                base_plan.get("regionalConfigs", []),
                availability_key="newSubscriberAvailability",
            )
            for price in prices:
                print(f"    {price}")

            other_regions = base_plan.get("otherRegionsConfig", {})
            if other_regions:
                print(
                    "    Other regions: "
                    f"{format_money(other_regions.get('usdPrice'))} / "
                    f"{format_money(other_regions.get('eurPrice'))}"
                )


def price_from_legacy_product(product):
    default_price = product.get("defaultPrice")
    if default_price:
        return [f"Default: {format_money(default_price)}"]

    prices = []
    for region_code, price in sorted(product.get("prices", {}).items()):
        if PRICE_REGIONS and region_code not in PRICE_REGIONS:
            continue
        prices.append(f"{region_code}: {format_money(price)}")

    if PRICE_REGIONS and not prices:
        prices.append(f"No prices found for regions: {', '.join(PRICE_REGIONS)}")

    return prices


def print_legacy_in_app_products(products):
    print("\nLegacy in-app products")
    if not products:
        print("- None")
        return

    for product in products:
        print(
            f"- {product.get('sku')} | {product.get('defaultLanguage', 'N/A')} "
            f"| type: {product.get('purchaseType', 'UNKNOWN')} "
            f"| status: {product.get('status', 'UNKNOWN')}"
        )

        for price in price_from_legacy_product(product):
            print(f"    {price}")


def build_all_products(one_time_products, subscriptions, legacy_in_app_products):
    all_products = []

    for product in one_time_products:
        all_products.append(
            {
                "source": "monetization.onetimeproducts",
                "type": "one_time_product",
                "productId": product.get("productId"),
                "title": title_from_listings(product),
                "raw": product,
            }
        )

    for subscription in subscriptions:
        all_products.append(
            {
                "source": "monetization.subscriptions",
                "type": "subscription",
                "productId": subscription.get("productId"),
                "title": title_from_listings(subscription),
                "raw": subscription,
            }
        )

    existing_ids = {
        product.get("productId")
        for product in all_products
        if product.get("productId")
    }
    for product in legacy_in_app_products:
        sku = product.get("sku")
        if sku in existing_ids:
            continue

        all_products.append(
            {
                "source": "inappproducts",
                "type": product.get("purchaseType", "legacy_in_app_product"),
                "productId": sku,
                "title": product.get("defaultLanguage", "Untitled"),
                "raw": product,
            }
        )

    return all_products


def fetch_google_products():
    print("🔒 Authenticating with Google Play servers...")
    creds = get_credentials(SERVICE_ACCOUNT_FILE, SCOPES)

    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Accept": "application/json",
    }

    print(f"📡 Fetching catalog for package: {PACKAGE_NAME}...")
    print(f"👤 Service account: {creds.service_account_email}")

    one_time_products_url = (
        f"{BASE_URL}/applications/{PACKAGE_NAME}/oneTimeProducts"
    )
    subscriptions_url = (
        f"{BASE_URL}/applications/{PACKAGE_NAME}/subscriptions"
    )
    legacy_in_app_products_url = (
        f"{BASE_URL}/applications/{PACKAGE_NAME}/inappproducts"
    )

    print("\n📦 Fetching one-time products...")
    one_time_products = list_paginated_resource(
        "One-time products",
        one_time_products_url,
        headers,
        "oneTimeProducts",
    )

    print("\n🔁 Fetching subscriptions...")
    subscriptions = list_paginated_resource(
        "Subscriptions",
        subscriptions_url,
        headers,
        "subscriptions",
    )

    print("\n🧾 Fetching legacy in-app products...")
    legacy_in_app_products = list_token_paginated_resource(
        "Legacy in-app products",
        legacy_in_app_products_url,
        headers,
        "inappproduct",
    )
    if legacy_in_app_products is None:
        print("⚠️  Skipping legacy in-app products and using the new publishing APIs.")
        legacy_in_app_products = []

    if one_time_products is None or subscriptions is None:
        print("\n403/permission checklist:")
        print(
            "- Invite the service-account email above in Google Play Console > Users and permissions."
        )
        print(
            "- Grant it access to this exact app/package, or grant account-level app access."
        )
        print(
            "- Grant permissions that allow viewing/managing app and monetization data."
        )
        print(
            "- Confirm Google Play Developer API is enabled in the Google Cloud project that owns this service account."
        )
        print("- Confirm PACKAGE_NAME exactly matches the Play Console package name.")
        sys.exit(1)

    all_products = build_all_products(
        one_time_products,
        subscriptions,
        legacy_in_app_products,
    )

    products_data = {
        "packageName": PACKAGE_NAME,
        "oneTimeProducts": one_time_products,
        "subscriptions": subscriptions,
        "legacyInAppProducts": legacy_in_app_products,
        "allProducts": all_products,
    }

    print(
        f"\n✅ Success! Found {len(one_time_products)} one-time products "
        f"and {len(subscriptions)} subscriptions, "
        f"{len(legacy_in_app_products)} legacy in-app products, "
        f"{len(all_products)} total unique products:"
    )
    print_one_time_products(one_time_products)
    print_subscriptions(subscriptions)
    print_legacy_in_app_products(legacy_in_app_products)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as output:
        json.dump(products_data, output, indent=4, ensure_ascii=False)
    print(f"\nFull JSON saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    fetch_google_products()
