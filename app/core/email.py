from fastapi.concurrency import run_in_threadpool
import resend
from app.core.config import settings

resend.api_key = settings.RESEND_API_KEY


def get_reset_email_html(reset_link: str) -> str:
    return f"""
    <div style="max-width:560px;margin:0 auto;font-family:sans-serif;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #eee;">
      <div style="background:#4f46e5;padding:2rem;text-align:center;">
        <img src="https://www.lexis.uz/header.png" alt="Lexis" style="max-height:48px;" />
      </div>
      <div style="padding:2rem 2.5rem;">
        <p style="color:#666;margin:0 0 0.5rem;">Assalomu alaykum,</p>
        <h2 style="font-size:20px;font-weight:500;margin:0 0 1rem;">Password recovery</h2>
        <p style="font-size:14px;color:#666;line-height:1.7;margin:0 0 1.5rem;">
          A password reset request has been received for your account.
          Set a new password by clicking the button below.
        </p>
        <div style="text-align:center;margin:1.5rem 0;">
          <a href="{reset_link}"
             style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;
                    padding:0.75rem 2rem;border-radius:6px;font-size:15px;">
            Reset password
          </a>
        </div>
        <div style="background:#f9f9f9;border-radius:6px;padding:1rem;margin:1.5rem 0;">
          <p style="font-size:12px;color:#999;margin:0 0 4px;">Or copy the link into your browser:</p>
          <p style="font-size:12px;color:#4f46e5;margin:0;word-break:break-all;">{reset_link}</p>
        </div>
        <div style="border-top:1px solid #eee;padding-top:1rem;margin-top:1.5rem;">
          <p style="font-size:12px;color:#999;margin:0 0 4px;">This link is valid for <strong>30 minutes</strong>.</p>
          <p style="font-size:12px;color:#999;margin:0;">If you did not request this, please ignore the email.</p>
        </div>
      </div>
      <div style="background:#f9f9f9;padding:1rem 2.5rem;text-align:center;border-top:1px solid #eee;">
        <p style="font-size:12px;color:#bbb;margin:0;">&copy; 2026 Lexis. All rights reserved.</p>
        <p style="font-size:12px;margin:4px 0 0;">
          <a href="https://lexis.uz" style="color:#4f46e5;text-decoration:none;">lexis.uz</a>
        </p>
      </div>
    </div>
    """


async def send_email(to: str, subject: str, body: str) -> None:
    payload = {
        "from": f"Lexis <{settings.MAIL_FROM}>",  # test uchun OK
        "to": [to],
        "subject": subject,
        "html": body,
    }

    try:
        response = await run_in_threadpool(resend.Emails.send, payload)
        print(f"Email sent: {response}")
    except Exception as e:
        print(f"Email failed to {to}: {e}")
        raise
