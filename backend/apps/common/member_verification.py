import json
from dataclasses import asdict, dataclass
from pathlib import Path
from django.conf import settings

@dataclass(frozen=True)
class VerificationPolicy:
    email_enabled: bool = True
    phone_enabled: bool = False
    require_phone: bool = True
    require_address: bool = True

def _path(): return Path(settings.BASE_DIR) / "config" / "verification_policy.json"

def get_verification_policy(system_key="stock"):
    try: return VerificationPolicy(**json.loads(_path().read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError): return VerificationPolicy()

def verification_policy_payload(system_key="stock"):
    p = get_verification_policy(system_key)
    return {"emailEnabled": p.email_enabled, "phoneEnabled": p.phone_enabled, "requirePhone": p.require_phone, "requireAddress": p.require_address}

def save_verification_policy(system_key, incoming, *, updated_by=""):
    p = VerificationPolicy(bool(incoming.get("emailEnabled")), bool(incoming.get("phoneEnabled")), bool(incoming.get("requirePhone")), bool(incoming.get("requireAddress")))
    _path().write_text(json.dumps(asdict(p), ensure_ascii=False, indent=2), encoding="utf-8")
    return verification_policy_payload(system_key)
