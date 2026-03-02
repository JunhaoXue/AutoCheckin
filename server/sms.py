"""Send SMS via Aliyun to wake phone screen."""

import json
import os
import random
import string
import logging

from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
from alibabacloud_tea_util import models as util_models

logger = logging.getLogger("autocheckin.sms")


class SMSService:
    def __init__(self):
        self.access_key_id = os.getenv("ALIYUN_ACCESS_KEY_ID", "")
        self.access_key_secret = os.getenv("ALIYUN_ACCESS_KEY_SECRET", "")
        self.sign_name = os.getenv("ALIYUN_SMS_SIGN_NAME", "")
        self.template_code = os.getenv("ALIYUN_SMS_TEMPLATE_CODE", "")
        self.phone_number = os.getenv("SMS_PHONE_NUMBER", "")
        self.client = None

        if all([self.access_key_id, self.access_key_secret, self.sign_name, self.template_code]):
            config = open_api_models.Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret,
                endpoint="dysmsapi.aliyuncs.com"
            )
            self.client = DysmsapiClient(config)
            logger.info(f"SMS service initialized (phone: {self.phone_number})")
        else:
            logger.info("SMS service disabled (missing env vars)")

    def send_wake_sms(self, phone: str = None) -> dict:
        """Send an SMS to wake the phone screen."""
        phone = phone or self.phone_number
        if not phone:
            return {"success": False, "error": "no phone number"}
        if not self.client:
            return {"success": False, "error": "SMS not configured"}

        code = ''.join(random.choices(string.digits, k=6))
        try:
            request = dysmsapi_models.SendSmsRequest(
                sign_name=self.sign_name,
                template_code=self.template_code,
                phone_numbers=phone,
                template_param=json.dumps({"code": code})
            )
            response = self.client.send_sms_with_options(request, util_models.RuntimeOptions())

            if response.body.code == "OK":
                logger.info(f"Wake SMS sent to {phone}")
                return {"success": True}
            else:
                logger.warning(f"SMS failed: {response.body.code} - {response.body.message}")
                return {"success": False, "error": response.body.message}
        except Exception as e:
            logger.error(f"SMS exception: {e}")
            return {"success": False, "error": str(e)}


sms_service = SMSService()
