import logging
from .tasks import send_email_task, send_sms_task

logger = logging.getLogger(__name__)

def send_otp_email(email, otp_code, sync=False):
    func = send_email_task if sync else send_email_task.delay
    func(
        subject="Your OTP Code",
        message=f"Your OTP code is {otp_code}",
        recipient_list=[email],
        html_message_path="users/emails/otp_email.html",
        context={"otp_code": otp_code}
    )

def send_welcome_email(email, user_name, sync=False):
    func = send_email_task if sync else send_email_task.delay
    func(
        subject="Welcome to Real Estate App!",
        message=f"Welcome {user_name}!",
        recipient_list=[email],
        html_message_path="users/emails/welcome_email.html",
        context={"user_name": user_name, "login_url": "http://localhost:8000/api/v1/users/auth/login/"}
    )

def send_owner_approval_email(email, user_name, sync=False):
    func = send_email_task if sync else send_email_task.delay
    func(
        subject="Owner Request Approved!",
        message=f"Congratulations {user_name}, your owner request has been approved!",
        recipient_list=[email],
        html_message_path="users/emails/owner_approval_email.html",
        context={"user_name": user_name, "login_url": "http://localhost:8000/api/v1/users/auth/login/"}
    )

def send_phone_otp_sms(phone, otp, sync=False):
    """Trigger celery task to send phone OTP via SMS."""
    logger.info(f"Triggering SMS OTP for phone: {phone} (Sync: {sync})")
    func = send_sms_task if sync else send_sms_task.delay
    func(phone, f"Your Real Estate verification code is: {otp}. Valid for 15 minutes.")
