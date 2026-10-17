# FMIS Email Delivery

## Account ownership

Create one mailbox owned by the Office for Agricultural Services, not by a student, developer, or individual staff member. A suitable address is `fmis@your-official-domain`. The Office must control the recovery address, MFA device, password manager entry, billing account, and provider administration.

Use that mailbox or a provider-approved sender identity for `DEFAULT_FROM_EMAIL`. Store SMTP credentials only in the protected production `.env`; never place them in Git, screenshots, chat, or turnover documents.

## Required provider information

Ask the Office's email/domain administrator or chosen email provider for:

- SMTP hostname and port;
- SMTP username and an app-specific password or SMTP credential;
- whether TLS on port 587 or SSL on port 465 is required;
- the provider's exact SPF record;
- the provider-generated DKIM selector and public key;
- the approved DMARC reporting mailbox.

Do not invent SPF or DKIM values. They are provider- and domain-specific.

## Production configuration

Set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, and `DEFAULT_FROM_EMAIL` using `deployment.env.example` as the guide. Restart FMIS after changing them.

Run a delivery test:

```powershell
python manage.py test_fmis_email recipient@office-domain.gov.ph
```

Then create a temporary pending staff account and verify the complete first-login activation flow. Also test password recovery by both saved email and saved phone identifier. Confirm delivery to at least two different mailbox providers and check spam folders.

## DNS acceptance gate

Before launch, use the exact records issued by the provider and confirm:

- SPF passes for the envelope sender;
- DKIM passes for the visible From domain;
- DMARC alignment passes;
- the production sender is not using a personal Gmail/Yahoo account;
- the Office has documented how to rotate the SMTP credential and recover the mailbox.
