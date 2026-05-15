---
name: meta-whatsapp-allowlist
description: Diagnose and fix Meta WhatsApp Cloud API test-recipient allowlist problems. Use when a WhatsApp send fails with error #131030, "Recipient phone number not in allowed list", when a user needs to add any phone number to the Meta allowed recipients list, or when configuring a test/API Setup recipient for WhatsApp Cloud API notifications.
---

# Meta WhatsApp Allowlist

## Core Rule

For Meta WhatsApp Cloud API test numbers, outbound messages only reach verified recipient numbers on the app's allowed/test-recipient list. This is a Meta dashboard setting, not an app-code setting. There is no normal app-side API fix for `#131030`; guide the user through Meta's UI and OTP verification.

Production WhatsApp business phone numbers do not use the same small test-recipient allowlist. If the user is on a real production sender and still sees delivery failures, investigate template approval, opt-in, phone number formatting, WABA/phone-number ID mismatch, or Meta account status instead.

## Workflow

1. Identify the target number.
   - Ask for the phone number if it was not provided.
   - Normalize it to international format.
   - For app config fields, prefer digits only, e.g. `13102108416`.
   - For Meta UI, use the country selector plus the national number, or E.164 with `+` if the UI accepts it.

2. Confirm the failure mode.
   - Look for `#131030`, `Recipient phone number not in allowed list`, or equivalent localized text in logs.
   - In the Ewash Railway app, the useful log line looks like `Meta send failed status=400 body=...`.
   - Do not print access tokens, `DATABASE_URL`, app secrets, or other Railway variables.

3. Add the number in Meta.
   - Open Meta Developers.
   - Select the correct app.
   - Go to WhatsApp -> API Setup, Configuration, or Getting Started.
   - In the "Send and receive messages" / "Step 1: Select phone numbers" area, open the recipient `To` dropdown or `Manage phone number list`.
   - Add the target recipient phone number.
   - Complete Meta's OTP verification by WhatsApp or SMS on that recipient device.

4. Handle common blockers.
   - If the test recipient list is full, remove an unused recipient or move to a production WhatsApp business sender.
   - If the UI does not show "Manage phone number list", verify the user is in the correct Meta app and WhatsApp product page, and has sufficient app/business permissions.
   - If the number verifies but sends still fail, compare the exact webhook `wa_id` or inbound `messages[0].from` format to the number saved in app/admin config.
   - Ensure the app is sending from the same `META_PHONE_NUMBER_ID` shown in the Meta API Setup page where the recipient was allowlisted.

5. Retry and verify.
   - Trigger the app action again.
   - Confirm the logs no longer show `#131030`.
   - If Meta returns a different 400 error, switch diagnosis to that new error code instead of continuing allowlist troubleshooting.

## Ewash-Specific Notes

- The internal booking alert destination is configured at `/admin/notifications`.
- Save the destination phone as digits only.
- A booking confirmation sends the configured template to the saved staff number.
- An Esthétique add-on update also sends the configured template again.
- If the Meta test sender is still being used, every staff/test recipient must be verified in Meta before these notifications can arrive.

## Response Pattern

When answering the user, be concrete:

- State whether the app attempted to send the message if logs prove it did.
- Quote only the non-secret Meta error code and reason.
- Give the exact Meta UI path.
- Tell the user the fix applies to whatever target number they want to add, not just one specific number.
- Mention when switching to a production WhatsApp sender removes the test-recipient allowlist constraint.
