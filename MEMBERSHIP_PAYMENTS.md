Membership checkout uses the gym's own UPI QR and owner verification.

1. In the owner Payments screen, open Configure payment QR.
2. Enter the payee/business name and tap Upload PhonePe / BHIM QR.
   Select the original reusable merchant QR from photos. The app validates the
   QR and reads its UPI ID. Preview the image, verify the recipient, then save.
   Alternatively, enter a UPI ID to generate a QR without uploading an image.
3. Check that the QR points to the intended gym account, then enable payments.
4. Members choose a plan, pay by the uploaded QR or their UPI app, and submit the transaction reference.
5. The owner verifies the reference and amount in the bank or UPI app and approves
   or rejects it in Payments > QR payments to verify.
6. Approval records the payment and activates or renews the membership. Submission
   alone never activates a plan. No automatic bank confirmation is claimed.

UPI checkout supports plans priced in INR. Same-plan renewals preserve remaining
membership days; a different plan starts upon approval. Price and duration are
validated on the server. Duplicate references and repeat approvals are rejected.
Payment records remain available in member and owner history.

No payment-provider credentials or webhook setup is needed. No database migration
is required. Existing payment records are retained. Automated tests do not transfer
money; QR-recipient accuracy and real-device UPI behavior require verification
with the gym's account and payment app.

Uploaded QR images are normalized and stored in the gym settings as bounded image data,
so no external file storage setup is needed. Uploads must contain a readable reusable
INR UPI QR with one recipient and no fixed amount. Requires Pillow and zxing-cpp on
the backend, and expo-image-picker / expo-image-manipulator on the frontend.
Rebuild custom native clients after installing the new Expo modules.
