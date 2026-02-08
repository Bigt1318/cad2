"""
FORD-CAD Theme System — API Routes
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from . import models
import json
import logging

log = logging.getLogger("themes")

def register_theme_routes(app: FastAPI):
    models.init_schema()
    log.info("[Themes] Routes registered")

    @app.get("/api/themes")
    async def api_get_themes(request: Request):
        """Get all themes + active slot for current user."""
        user_id = request.session.get("unit", "DISPATCH")
        themes = models.get_all_themes(user_id)
        active_slot = models.get_active_slot(user_id)
        presets = [{"name": k, "tokens": v} for k, v in models.DEFAULT_PRESETS.items()]
        return JSONResponse({
            "ok": True,
            "themes": themes,
            "active_slot": active_slot,
            "presets": presets
        })

    @app.get("/api/themes/active")
    async def api_get_active_theme(request: Request):
        """Get the active theme tokens for the current user."""
        user_id = request.session.get("unit", "DISPATCH")
        active_slot = models.get_active_slot(user_id)
        if active_slot == 0:
            return JSONResponse({"ok": True, "slot": 0, "tokens": {}, "name": "System Default"})
        theme = models.get_theme(user_id, active_slot)
        if not theme:
            return JSONResponse({"ok": True, "slot": 0, "tokens": {}, "name": "System Default"})
        return JSONResponse({
            "ok": True,
            "slot": theme["slot"],
            "name": theme["name"],
            "tokens": theme["tokens"]
        })

    @app.post("/api/themes/active")
    async def api_set_active_slot(request: Request):
        """Set which slot is active (0 = system default)."""
        user_id = request.session.get("unit", "DISPATCH")
        body = await request.json()
        slot = body.get("slot", 0)
        if not isinstance(slot, int) or slot < 0 or slot > 5:
            return JSONResponse({"ok": False, "error": "Slot must be 0-5"}, status_code=400)
        models.set_active_slot(user_id, slot)
        return JSONResponse({"ok": True, "active_slot": slot})

    @app.post("/api/themes/save")
    async def api_save_theme(request: Request):
        """Save a theme to a slot. Auto-save endpoint."""
        user_id = request.session.get("unit", "DISPATCH")
        body = await request.json()
        slot = body.get("slot", 1)
        name = body.get("name", "My Theme")
        tokens = body.get("tokens", {})
        if not isinstance(slot, int) or slot < 1 or slot > 5:
            return JSONResponse({"ok": False, "error": "Slot must be 1-5"}, status_code=400)
        if not isinstance(tokens, dict):
            return JSONResponse({"ok": False, "error": "Tokens must be object"}, status_code=400)
        models.save_theme(user_id, slot, name, tokens)
        # Auto-activate the slot being saved
        models.set_active_slot(user_id, slot)
        return JSONResponse({"ok": True, "slot": slot, "name": name})

    @app.post("/api/themes/reset")
    async def api_reset_theme(request: Request):
        """Reset a slot to empty / delete it."""
        user_id = request.session.get("unit", "DISPATCH")
        body = await request.json()
        slot = body.get("slot", 1)
        if not isinstance(slot, int) or slot < 1 or slot > 5:
            return JSONResponse({"ok": False, "error": "Slot must be 1-5"}, status_code=400)
        models.delete_theme(user_id, slot)
        return JSONResponse({"ok": True})

    @app.post("/api/themes/duplicate")
    async def api_duplicate_theme(request: Request):
        """Duplicate from one slot to another."""
        user_id = request.session.get("unit", "DISPATCH")
        body = await request.json()
        from_slot = body.get("from_slot")
        to_slot = body.get("to_slot")
        if not from_slot or not to_slot:
            return JSONResponse({"ok": False, "error": "Need from_slot and to_slot"}, status_code=400)
        ok = models.duplicate_theme(user_id, from_slot, to_slot)
        if not ok:
            return JSONResponse({"ok": False, "error": "Source theme not found"}, status_code=404)
        return JSONResponse({"ok": True})

    @app.post("/api/themes/export")
    async def api_export_theme(request: Request):
        """Export a theme as JSON."""
        user_id = request.session.get("unit", "DISPATCH")
        body = await request.json()
        slot = body.get("slot", 1)
        theme = models.get_theme(user_id, slot)
        if not theme:
            return JSONResponse({"ok": False, "error": "Theme not found"}, status_code=404)
        return JSONResponse({
            "ok": True,
            "export": {
                "name": theme["name"],
                "tokens": theme["tokens"],
                "exported_at": theme["updated_at"],
                "version": 1
            }
        })

    @app.post("/api/themes/import")
    async def api_import_theme(request: Request):
        """Import a theme from JSON into a slot."""
        user_id = request.session.get("unit", "DISPATCH")
        body = await request.json()
        slot = body.get("slot", 1)
        theme_data = body.get("theme", {})
        name = theme_data.get("name", "Imported Theme")
        tokens = theme_data.get("tokens", {})
        if not isinstance(tokens, dict) or not tokens:
            return JSONResponse({"ok": False, "error": "Invalid theme data"}, status_code=400)
        models.save_theme(user_id, slot, name, tokens)
        return JSONResponse({"ok": True, "slot": slot, "name": name})

    @app.get("/api/themes/presets")
    async def api_get_presets(request: Request):
        """Get built-in theme presets."""
        presets = [{"name": k, "tokens": v} for k, v in models.DEFAULT_PRESETS.items()]
        return JSONResponse({"ok": True, "presets": presets})

    @app.get("/modals/themes")
    async def modal_themes(request: Request):
        """Serve the theme editor modal HTML."""
        templates = app.state.templates
        user_id = request.session.get("unit", "DISPATCH")
        themes = models.get_all_themes(user_id)
        active_slot = models.get_active_slot(user_id)
        presets = list(models.DEFAULT_PRESETS.keys())
        return templates.TemplateResponse("themes/editor_modal.html", {
            "request": request,
            "themes": themes,
            "active_slot": active_slot,
            "presets": presets
        })
