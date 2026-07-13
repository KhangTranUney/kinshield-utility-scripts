# Android Billing Setup Guide

This guide explains how to configure Google Play Billing for an Android app,
including Play Console setup, in-app products, subscriptions, backend API access,
Real-time Developer Notifications (RTDN), and local testing.

## Prerequisites

- A Google Play Developer account.
- An Android app created in Google Play Console.
- An Android App Bundle (AAB) that includes the Google Play Billing Library.
- A Google Cloud project for service account access and RTDN.
- Tester Gmail accounts for license testing and internal testing.

## 1. Configure License Testing

1. Open Google Play Console.
2. Go to **Setup > License testing**.
3. Add the Gmail addresses of your test users in the **License testers** field.
4. Set **License response** to **RESPOND_NORMALLY**.
5. Save the changes.

When these accounts make purchases from test tracks, Google Play shows a test
payment window and charges `0.00`.

## 2. Set Up a Payments Profile

1. In Google Play Console, go to **Settings > Payments profile**.
2. Create a payments profile if one does not exist.
3. For test setup, complete the basic address information.

Bank verification, tax forms, and business ID uploads are not required for basic
test product creation, but they are required before production monetization.

## 3. Create the App in Google Play Console

1. Open Google Play Console.
2. Click **Create app**.
3. Enter the app name, default language, app/game type, and free/paid status.
4. Complete the required declarations.
5. Click **Create app**.

## 4. Add Google Play Billing to the Android App

Add the Google Play Billing Library dependency to the app module.

### Kotlin DSL

```kotlin
dependencies {
    val billingVersion = "9.1.0"
    implementation("com.android.billingclient:billing:$billingVersion")
}
```

### Groovy

```groovy
dependencies {
    def billingVersion = "9.1.0"
    implementation "com.android.billingclient:billing:$billingVersion"
}
```

Always check the official release notes before implementation and use a supported
Billing Library version.

After adding the dependency:

1. Build a release Android App Bundle (`.aab`).
2. Upload it to a testing track, such as **Internal testing** or **Closed
   testing**.
3. Publish the testing release.

Google Play Billing features are available only after Google Play has processed
an app version that includes the Billing Library.

## 5. Create One-Time Products

Use one-time products for consumables and non-consumables.

1. In Google Play Console, open the app.
2. Go to **Monetize > Products > One-time products**.
3. Click **Create product**.
4. Enter a unique product ID, for example `premium_upgrade_01` or `100_coins`.
5. Enter the title and description shown to users at checkout.
6. Set the price.
7. Click **Save**.
8. Click **Activate**.

Important: Product IDs cannot be changed or reused after creation. Choose stable
IDs that can remain valid for the lifetime of the app.

## 6. Create Subscriptions

Use subscriptions for recurring access.

1. In Google Play Console, open the app.
2. Go to **Monetize > Products > Subscriptions**.
3. Click **Create subscription**.
4. Enter the product ID and name.
5. Open the subscription and click **Add base plan**.
6. Select the billing frequency, such as weekly, monthly, or yearly.
7. Choose the base plan type, such as auto-renewing or prepaid.
8. Set the pricing.
9. Click **Activate**.

## 7. Create a Google Cloud Service Account

Create a service account when your backend needs to call Google Play Developer
API endpoints such as purchase verification or subscription lookup.

1. Open Google Cloud Console.
2. Go to **IAM & Admin > Service Accounts**.
3. Click **Create service account**.
4. Enter a name, for example `play-billing-api`.
5. Click **Create and continue**.
6. Assign a basic role such as **Viewer** if your organization requires a role.
   Add **Storage Object Viewer** only if the service account must read files from
   Cloud Storage.
7. Click **Done**.
8. Open the service account.
9. Go to the **Keys** tab.
10. Click **Add key > Create new key**.
11. Select **JSON** and download the key file.
12. Copy the service account email address, for example
    `play-billing-api@your-project.iam.gserviceaccount.com`.

Keep the JSON key secure. Do not commit it to source control.

## 8. Grant Google Play Console Permissions to the Service Account

Google Play API permissions are configured in Play Console, not only in Google
Cloud IAM.

1. Log in to Google Play Console as the account owner or an admin with user
   management access.
2. Go to **Users and permissions**.
3. Click **Invite new users**.
4. Paste the service account email address.
5. Open the **App permissions** tab.
6. Click **Add app** and select the target app.
7. Enable the permissions required by your backend:
   - **View financial data, orders, and cancellation survey responses**
   - **Manage orders and subscriptions**, if the backend manages orders,
     subscriptions, or acknowledgements
8. Open the **Account permissions** tab if your account requires global financial
   access.
9. In the **Financial data** section, enable **View financial data, orders, and
   cancellation survey responses**.
10. Click **Invite user**.

Use the minimum permissions needed for the backend workflow.

## 9. Configure Real-Time Developer Notifications

RTDN sends Google Play purchase and subscription events to your backend through
Google Cloud Pub/Sub.

### 9.1 Find the Google Cloud Project ID

Use the same Google Cloud project connected to your Google Play API setup.

If you already have a service account JSON file, open it and find the
`project_id` value.

Example:

```json
{
  "project_id": "my-awesome-app-1234"
}
```

### 9.2 Create the Pub/Sub Topic

1. Open Google Cloud Console.
2. Select the project from the project selector.
3. Go to **Pub/Sub > Topics**.
4. Click **Create topic**.
5. Enter a topic ID, for example `play-rtdn`.
6. Leave **Use a default subscription** unchecked.
7. Click **Create**.

### 9.3 Create a Push Subscription

1. Open the `play-rtdn` topic.
2. Go to the **Subscriptions** tab.
3. Click **Create subscription**.
4. Enter a subscription ID, for example `play-rtdn-sub`.
5. Set **Delivery type** to **Push**.
6. Enter the backend endpoint URL, for example
   `https://api.yourdomain.com/v1/webhooks/google-play`.
7. Enable authentication if your backend validates Pub/Sub push tokens.
8. Select the service account used to sign push requests.
9. Enter the expected audience value. This is usually the endpoint URL or a
   backend-specific audience string.
10. Click **Create**.

Share the push service account email and audience value with the backend team so
the endpoint can validate incoming requests.

### 9.4 Link the Topic in Google Play Console

1. Open Google Play Console.
2. Select the app.
3. Go to **Monetize > Monetization setup**.
4. Find **Real-time developer notifications**.
5. Enter the full topic name:

```text
projects/YOUR_PROJECT_ID/topics/play-rtdn
```

6. Click **Send test notification**.
7. Click **Save changes** after the test succeeds.

During this step, Google Play usually grants the Pub/Sub Publisher role to:

```text
google-play-developer-notifications@system.gserviceaccount.com
```

### 9.5 Verify Pub/Sub Permissions

If the test notification fails:

1. Open Google Cloud Console.
2. Go to **Pub/Sub > Topics**.
3. Open the `play-rtdn` topic.
4. Open the permissions panel. If it is hidden, click **Show info panel**.
5. Verify that the following principal exists:

```text
google-play-developer-notifications@system.gserviceaccount.com
```

6. Confirm it has the **Pub/Sub Publisher** role.

If it is missing, add it manually:

1. Click **Add principal**.
2. Paste `google-play-developer-notifications@system.gserviceaccount.com`.
3. Assign **Pub/Sub > Pub/Sub Publisher**.
4. Click **Save**.

Note: This Google-managed service account may not appear in autocomplete. Paste
the full email address.

## 10. Local Testing Rules

Local billing tests can work with debug builds when the following conditions are
met:

1. The package name matches the app in Google Play Console.
   - The local `applicationId` must exactly match the Play Console package name,
     for example `com.yourcompany.yourapp`.
2. The version code is valid.
   - The local `versionCode` should match or be higher than the version code
     uploaded to the active testing track.
3. The device uses a license tester account.
   - The Google Play Store account on the test device must be one of the Gmail
     addresses configured in **Setup > License testing**.
4. The tester has joined the testing track.
   - For internal or closed testing, the tester must open the opt-in link and
     join the test before purchasing.

After publishing a test release, Google Play may take a few hours to make it
available to testers.

## 11. Troubleshooting

### RTDN Test Notification Fails

Check that:

- The Pub/Sub topic exists in the correct Google Cloud project.
- The topic name in Play Console uses the correct format:
  `projects/YOUR_PROJECT_ID/topics/play-rtdn`.
- `google-play-developer-notifications@system.gserviceaccount.com` has the
  **Pub/Sub Publisher** role on the topic.
- The push endpoint is reachable from the internet.
- The backend accepts the configured authentication audience.

### Domain Restricted Sharing Blocks Permission Changes

If Google Cloud shows an error similar to:

```text
One or more users named in the policy do not belong to a permitted customer
```

then the organization may have Domain Restricted Sharing enabled.

To allow the Google-managed service account:

1. Open Google Cloud Console.
2. Search for **Organization Policies**.
3. Open **Domain restricted sharing** (`iam.allowedPolicyMemberDomains`).
4. Edit the policy.
5. Add an allowed rule for `system.gserviceaccount.com`, or temporarily allow all
   principals if your organization policy allows that.
6. Save the policy.
7. Return to the Pub/Sub topic and add the Google Play service account again.

Coordinate this change with the organization administrator if you do not manage
organization policies.

### Backend API Calls Return Permission Denied

If the backend receives `403 Permission Denied` or cannot validate subscription
API permissions:

- Confirm the service account is invited in **Users and permissions** in Google
  Play Console.
- Confirm it has app-level access to the target app.
- Confirm it has the financial/order permissions required by the API endpoint.
- Wait for permissions to propagate.
- Re-save one in-app product or subscription in Play Console to force product
  metadata refresh if propagation appears delayed.

## 12. Final Checklist

- License testers are configured.
- A payments profile exists.
- The app has been created in Google Play Console.
- A billing-enabled AAB has been uploaded to a testing track.
- One-time products or subscriptions are created and activated.
- Backend service account permissions are configured in Play Console.
- RTDN Pub/Sub topic and push subscription are configured.
- Google Play has Pub/Sub Publisher access to the RTDN topic.
- Test users have joined the testing track.
- Test purchases complete successfully.

