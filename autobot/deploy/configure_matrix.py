"""Apply the local deployment settings to upstream-generated YAML files."""
import os
import secrets
import sys
from pathlib import Path

import yaml


ROOT = Path("/setup")
BRIDGE = ROOT / "mautrix/config.yaml"
SYNAPSE = ROOT / "synapse/homeserver.yaml"


def read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    path.chmod(0o600)


def configure(domain):
    if (ROOT / "mautrix/registration.yaml").exists():
        raise SystemExit("Đã có registration.yaml; không chạy lại bootstrap trên hệ thống đang sử dụng.")
    bridge = read(BRIDGE)
    bridge["homeserver"].update(address="http://synapse:8008", domain=domain,
                                status_endpoint="http://autobot:8080/internal/meta-status")
    bridge["appservice"].update(address="http://mautrix-meta:29319", hostname="0.0.0.0", port=29319,
                                public_address="", ephemeral_events=False)
    bridge["appservice"]["bot"]["username"] = "facebookbot"
    bridge["appservice"]["username_template"] = "facebook_{{.}}"
    bridge["database"].update(type="sqlite3-fk-wal", uri="file:/data/mautrix-meta.db?_txlock=immediate")
    bridge["bridge"].update(permissions={f"@bridgeowner:{domain}": "user"}, bridge_matrix_leave=False,
                            bridge_status_notices="errors", bridge_notices=False, kick_matrix_users=False)
    bridge["bridge"]["relay"]["enabled"] = False
    bridge["matrix"].update(federate_rooms=False, delivery_receipts=False)
    bridge["double_puppet"].update(allow_discovery=False, servers={}, secrets={})
    bridge["encryption"].update(allow=False, default=False, require=False)
    bridge["backfill"]["enabled"] = False
    bridge["network"].update(e2ee_backfill=False, send_presence_on_typing=False)
    bridge["logging"].update(min_level="info", writers=[{"type": "stdout", "format": "json"}])
    bridge["provisioning"].update(shared_secret="disable", allow_matrix_auth=False)
    write(BRIDGE, bridge)

    synapse = read(SYNAPSE)
    if synapse["server_name"] != domain:
        raise SystemExit("MATRIX_DOMAIN phải khớp SYNAPSE_SERVER_NAME khi generate.")
    synapse.update(enable_registration=False, enable_registration_without_verification=False,
                   registration_shared_secret=secrets.token_urlsafe(48),
                   federation_domain_whitelist=[], app_service_config_files=["/data/mautrix-registration.yaml"],
                   url_preview_enabled=False, allow_guest_access=False)
    for listener in synapse["listeners"]:
        listener["resources"] = [{"names": ["client"], "compress": False}]
    write(SYNAPSE, synapse)
    os.chown(SYNAPSE, 991, 991)


def install_registration():
    registration = read(ROOT / "mautrix/registration.yaml")
    if registration.get("as_token") != read(BRIDGE).get("appservice", {}).get("as_token"):
        raise SystemExit("Appservice token không khớp config bridge.")
    target = ROOT / "synapse/mautrix-registration.yaml"
    write(target, registration)
    os.chown(target, 991, 991)
    status = ROOT / "status/meta-as-token"
    status.write_text(registration["as_token"], encoding="utf-8")
    status.chmod(0o400)
    os.chown(status, 10001, 10001)
    os.chown(status.parent, 10001, 10001)


if __name__ == "__main__":
    if sys.argv[1:] == ["configure"]:
        configure(os.environ["MATRIX_DOMAIN"])
    elif sys.argv[1:] == ["register"]:
        install_registration()
    else:
        raise SystemExit("Dùng configure hoặc register.")
