import os

import firebase_admin
from firebase_admin import credentials, firestore

from app.core.config import settings


def initialize_firebase() -> bool:
    try:
        if not settings.use_firebase:
            return False

        if firebase_admin._apps:
            return True

        if settings.firebase_credentials_file and os.path.exists(settings.firebase_credentials_file):
            cred = credentials.Certificate(settings.firebase_credentials_file)
            firebase_admin.initialize_app(
                cred,
                {"projectId": settings.firebase_project_id},
            )
            return True

        if (
            settings.firebase_private_key
            and settings.firebase_client_email
            and settings.firebase_private_key != "your_private_key_here"
        ):
            private_key = settings.firebase_private_key.replace("\\n", "\n")
            service_account_info = {
                "type": "service_account",
                "project_id": settings.firebase_project_id,
                "private_key": private_key,
                "client_email": settings.firebase_client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(
                cred,
                {"projectId": settings.firebase_project_id},
            )
            return True

        return False
    except Exception as exc:
        print(f"Firebase initialization error: {exc}")
        return False


def get_db() -> firestore.Client | None:
    if not firebase_initialized:
        return None

    try:
        return firestore.client()
    except Exception as exc:
        print(f"Error getting Firestore client: {exc}")
        return None


firebase_initialized = initialize_firebase()
