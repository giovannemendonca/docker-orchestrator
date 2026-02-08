import logging

from flask import Blueprint, request, redirect, jsonify

import services
import containers

logger = logging.getLogger(__name__)

bp = Blueprint("routes", __name__)


@bp.route("/access")
def access():
    client_id = request.args.get("id", "").strip()

    if not client_id:
        logger.warning("[ACCESS] Request with missing 'id' parameter")
        return jsonify({"error": "Missing required parameter: id"}), 400

    try:
        result = services.get_or_create_access(client_id)
    except ValueError as e:
        return jsonify({
            "error": str(e),
            "max_slots": containers.PORT_MAX - containers.PORT_MIN + 1,
        }), 503
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return redirect(result["url"])


@bp.route("/status")
def status():
    return jsonify(services.get_status())


@bp.route("/remove")
def remove():
    client_id = request.args.get("id", "").strip()

    if not client_id:
        logger.warning("[REMOVE] Request with missing 'id' parameter")
        return jsonify({"error": "Missing required parameter: id"}), 400

    result = services.remove_client(client_id)

    if result is None:
        return jsonify({"error": f"No container found for id {client_id}"}), 404

    return jsonify(result)


@bp.route("/remove-all")
def remove_all():
    return jsonify(services.remove_all_clients())


@bp.route("/health")
def health():
    return jsonify({"status": "ok"})
