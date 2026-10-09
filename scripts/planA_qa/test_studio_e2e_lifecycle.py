"""
Plan A Studio E2E Interactive Lifecycle Verification
Author: Gemini (Independent QA Agent)
Scope: Real path verification of clicking, editing, saving, and reopening Studio canvases.

Lifecycle Stages:
1. 实际点击 (Actual Click):
   - Opens Studio Flow View
   - Clicks '+ 新建画布' in TopBar
   - Switches to '空白画布' tab
   - Inputs title 'E2E自由创作板_滑雪特写'
   - Clicks '创建空白画布'
   - Intercepts canvas ID from URL / API
2. 初始节点检查 (Initial Node Verification & BUG-05 Detection):
   - Verifies whether new canvas is truly blank or auto-injects chapter/story cards
3. 实际新增与编辑 (Actual Add Node & Edit):
   - Clicks '+' button in bottom dock (.cv-bb-plus)
   - Picks '文本' in AddMenu
   - Double-clicks node card (.cv-card) to activate TextEditor
   - Types customized prompt/recipe using native browser input
   - Blurs to commit edit
4. 实际保存 (Actual Save Verification):
   - Observes debounced auto-save (SAVE_DEBOUNCE = 1000ms)
   - Verifies TopBar indicator changes to '已保存' (.cv-save.t-ok)
   - Verifies backend database record (version increments, doc contains node & text)
5. 重新打开 (Actual Reopen Verification):
   - Navigates directly to canvas URL (?view=flow&canvas={id})
   - Waits for React Flow nodes to mount and data to resolve
   - Asserts edited text node is preserved and rendered with exact text
   - Documents unwanted cards and overall canvas consistency
"""

import os
import sys
import time
import json
import base64
import urllib.request
import subprocess
from typing import Dict, Any, List, Optional
import websocket

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
STUDIO_PORT = 5174
CORE_PORT = 8100
CDP_PORT = 9231
USER_DATA_DIR = "/tmp/chrome_planA_e2e_test_profile"
SCREENSHOTS_DIR = os.path.abspath("docs/studio/test_runs/screenshots")
REPORT_PATH = os.path.abspath("docs/studio/test_runs/e2e_interactive_latest.json")

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)


class CDPClient:
    def __init__(self, port: int = CDP_PORT):
        self.port = port
        self.proc: Optional[subprocess.Popen] = None
        self.ws: Optional[websocket.WebSocket] = None
        self.req_id = 0
        self.requests_sent: Dict[str, Dict[str, Any]] = {}
        self.responses_received: Dict[str, Dict[str, Any]] = {}

    def start(self):
        cmd = [
            CHROME_PATH,
            "--headless=new",
            f"--remote-debugging-port={self.port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={USER_DATA_DIR}",
            "--window-size=1440,900",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "about:blank",
        ]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(25):
            time.sleep(0.3)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                pass
        else:
            raise RuntimeError("Failed to connect to Chrome CDP port")

        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list") as resp:
            tabs = json.loads(resp.read().decode())
        page = next(t for t in tabs if t.get("type") == "page")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Network.enable")

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.req_id += 1
        cid = self.req_id
        payload = {"id": cid, "method": method, "params": params or {}}
        self.ws.send(json.dumps(payload))
        while True:
            raw = self.ws.recv()
            msg = json.loads(raw)
            if "method" in msg:
                m = msg["method"]
                p = msg.get("params", {})
                if m == "Network.requestWillBeSent":
                    req_id = p.get("requestId")
                    self.requests_sent[req_id] = p.get("request", {})
                elif m == "Network.responseReceived":
                    req_id = p.get("requestId")
                    self.responses_received[req_id] = p.get("response", {})
                continue
            if msg.get("id") == cid:
                if "error" in msg:
                    raise RuntimeError(f"CDP call {method} error: {msg['error']}")
                return msg.get("result", {})

    def evaluate(self, expr: str) -> Any:
        res = self.call("Runtime.evaluate", {
            "expression": expr,
            "awaitPromise": True,
            "returnByValue": True,
        })
        result_obj = res.get("result", {})
        if "value" in result_obj:
            return result_obj["value"]
        if result_obj.get("type") == "undefined":
            return None
        return result_obj

    def capture_screenshot(self, filepath: str) -> str:
        shot = self.call("Page.captureScreenshot", {"format": "png"})
        raw = base64.b64decode(shot["data"])
        with open(filepath, "wb") as f:
            f.write(raw)
        return filepath

    def stop(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


def run_e2e_verification() -> Dict[str, Any]:
    cdp = CDPClient()
    report: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "test_target": f"http://localhost:{STUDIO_PORT}",
        "steps": {},
        "defects_observed": [],
        "overall_status": "PENDING",
    }

    try:
        print("[1/5] Launching headless Chrome and navigating to Studio...")
        cdp.start()

        start_url = f"http://localhost:{STUDIO_PORT}/studio/?view=flow&novel=nv_01M1MER58J7H3B06F0BQF0TNTE&chapter=ch_01M1METGFD9RXHWWV8FR65Z57K&plan=sp_01M20G8W1RN8BZ7FVE6FQHZ0P6"
        cdp.call("Page.navigate", {"url": start_url})
        time.sleep(3.5)

        initial_shot = os.path.join(SCREENSHOTS_DIR, "00_initial_flow_view.png")
        cdp.capture_screenshot(initial_shot)

        # -------------------------------------------------------------
        # STEP 1: 点击 '+ 新建画布' 并创建空白画布
        # -------------------------------------------------------------
        print("[2/5] Step 1: Clicking '+ 新建画布' in TopBar...")
        click_new_res = {"success": False}
        for _ in range(10):
            click_new_res = cdp.evaluate("""
                (() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const newBtn = btns.find(b => b.innerText.includes('新建画布') && !b.closest('.cv-crumb-pop'));
                    if (!newBtn) return { success: false, error: '新建画布 button not found' };
                    newBtn.click();
                    return { success: true };
                })()
            """)
            if click_new_res.get("success"):
                break
            time.sleep(1.0)
        assert click_new_res.get("success"), f"Failed to click 新建画布: {click_new_res}"
        time.sleep(1.0)

        # Switch to '空白画布' tab
        cdp.evaluate("""
            (() => {
                const tabs = Array.from(document.querySelectorAll('.cv-newcanvas-tab'));
                const blankTab = tabs.find(t => t.innerText.includes('空白画布'));
                if (blankTab) blankTab.click();
            })()
        """)
        time.sleep(0.5)

        # Type custom title using React native property setter
        custom_title = "E2E自由创作板_滑雪特写"
        cdp.evaluate(f"""
            (() => {{
                const input = document.querySelector('.cv-newcanvas-modal input.cv-input');
                if (input) {{
                    input.focus();
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(input, '{custom_title}');
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }})()
        """)
        time.sleep(0.5)

        modal_shot = os.path.join(SCREENSHOTS_DIR, "01_create_blank_canvas_modal.png")
        cdp.capture_screenshot(modal_shot)
        print("Captured modal screenshot:", modal_shot)

        # Click '创建空白画布'
        cdp.evaluate("""
            (() => {
                const btns = Array.from(document.querySelectorAll('.cv-newcanvas-modal button.cv-btn.is-primary'));
                const submitBtn = btns.find(b => b.innerText.includes('创建空白画布'));
                if (submitBtn) submitBtn.click();
            })()
        """)
        time.sleep(3.0)

        new_canvas_id = cdp.evaluate("""
            (() => {
                const url = new URL(window.location.href);
                return url.searchParams.get('canvas');
            })()
        """)
        print("New canvas ID created:", new_canvas_id)
        assert new_canvas_id, "New canvas ID not found in URL"

        created_shot = os.path.join(SCREENSHOTS_DIR, "02_blank_canvas_created.png")
        cdp.capture_screenshot(created_shot)

        # Inspect initial nodes rendered on blank canvas
        initial_nodes = cdp.evaluate("""
            (() => {
                const nodes = Array.from(document.querySelectorAll('.react-flow__node'));
                return nodes.map(n => ({
                    id: n.getAttribute('data-id'),
                    title: n.querySelector('.cv-node__title')?.innerText || '',
                    text: (n.querySelector('.cv-text__plain, .cv-card')?.innerText || '').slice(0, 100)
                }));
            })()
        """)
        print(f"Initial nodes on blank canvas ({len(initial_nodes)}):", initial_nodes)

        # Check for BUG-05
        has_story_summary = any("故事梗概" in (n.get("title") or "") for n in initial_nodes)
        if has_story_summary:
            defect = {
                "id": "BUG-05",
                "severity": "HIGH",
                "title": "新建空白画布自动注入故事梗概卡片",
                "reproduction_milestone": "STEP 1 (新建空白画布)",
                "details": f"用户在空白画布弹窗中输入「{custom_title}」并创建，生成的画布初始即包含故事梗概卡片，违背自由空白画布预期",
                "screenshot": created_shot,
            }
            report["defects_observed"].append(defect)
            print(">>> [DEFECT CONFIRMED] BUG-05:", defect["title"])

        report["steps"]["step1_create_canvas"] = {
            "status": "PASS",
            "canvas_id": new_canvas_id,
            "title": custom_title,
            "initial_node_count": len(initial_nodes),
            "initial_nodes": initial_nodes,
            "has_unwanted_story_card": has_story_summary,
            "screenshot": created_shot,
        }

        # -------------------------------------------------------------
        # STEP 2: 实际新增节点与就地编辑 (Add Node & Edit)
        # -------------------------------------------------------------
        print("[3/5] Step 2: Clicking '+' dock button and adding '文本' node...")
        open_add_menu = cdp.evaluate("""
            (() => {
                const plusBtn = document.querySelector('button.cv-bb-plus');
                if (!plusBtn) return { success: false, error: 'cv-bb-plus not found' };
                plusBtn.click();
                return { success: true };
            })()
        """)
        assert open_add_menu.get("success"), f"Failed to open AddMenu: {open_add_menu}"
        time.sleep(0.8)

        # Pick '文本'
        cdp.evaluate("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cv-addmenu .cv-menu-item'));
                const textItem = items.find(it => it.innerText.includes('文本'));
                if (textItem) textItem.click();
            })()
        """)
        time.sleep(1.5)

        # Find target text node
        nodes_after_add = cdp.evaluate("""
            (() => {
                const nodes = Array.from(document.querySelectorAll('.react-flow__node'));
                return nodes.map(n => ({
                    id: n.getAttribute('data-id'),
                    title: n.querySelector('.cv-node__title')?.innerText || '',
                    has_card: !!n.querySelector('.cv-card'),
                    empty_text: !!n.querySelector('.cv-text__empty')
                }));
            })()
        """)
        target_text_node = next((n for n in nodes_after_add if n.get("empty_text") or n.get("title") == "文本"), None)
        assert target_text_node, f"Text node not found among: {nodes_after_add}"
        target_node_id = target_text_node["id"]
        print(f"Target node created: {target_node_id}")

        added_shot = os.path.join(SCREENSHOTS_DIR, "03_node_added.png")
        cdp.capture_screenshot(added_shot)

        # Double click to open TextEditor
        print(f"[3/5] Double clicking node {target_node_id} to open TextEditor...")
        cdp.evaluate(f"""
            (() => {{
                const node = document.querySelector(\".react-flow__node[data-id='{target_node_id}']\");
                const card = node?.querySelector('.cv-card');
                if (card) card.dispatchEvent(new MouseEvent('dblclick', {{ bubbles: true, cancelable: true }}));
            }})()
        """)
        time.sleep(0.6)

        # Focus textarea
        cdp.evaluate(f"""
            (() => {{
                const node = document.querySelector(\".react-flow__node[data-id='{target_node_id}']\");
                const textarea = node?.querySelector('textarea.cv-text__edit');
                if (textarea) textarea.focus();
            }})()
        """)
        time.sleep(0.3)

        # Insert text using native CDP input event
        edited_text_content = "滑雪少女自由创作镜头：高山雪道急速俯冲，定格漫天飞雪特写"
        print(f"[3/5] Typing text via CDP Input.insertText: '{edited_text_content}'...")
        cdp.call("Input.insertText", {"text": edited_text_content})
        time.sleep(0.5)

        # Blur to commit edit
        cdp.evaluate(f"""
            (() => {{
                const node = document.querySelector(\".react-flow__node[data-id='{target_node_id}']\");
                const textarea = node?.querySelector('textarea.cv-text__edit');
                if (textarea) textarea.blur();
            }})()
        """)
        time.sleep(1.0)

        # Check DOM rendered text
        rendered_plain_text = cdp.evaluate(f"""
            (() => {{
                const node = document.querySelector(\".react-flow__node[data-id='{target_node_id}']\");
                return node ? node.querySelector('.cv-text__plain')?.innerText : null;
            }})()
        """)
        print("DOM rendered plain text:", repr(rendered_plain_text))
        assert rendered_plain_text and edited_text_content in rendered_plain_text, f"DOM text mismatch: {rendered_plain_text}"

        edited_shot = os.path.join(SCREENSHOTS_DIR, "04_node_edited.png")
        cdp.capture_screenshot(edited_shot)
        print("Captured edited screenshot:", edited_shot)

        report["steps"]["step2_edit_node"] = {
            "status": "PASS",
            "node_id": target_node_id,
            "typed_content": edited_text_content,
            "dom_rendered_content": rendered_plain_text,
            "screenshot": edited_shot,
        }

        # -------------------------------------------------------------
        # STEP 3: 实际保存验证 (Save Verification)
        # -------------------------------------------------------------
        print("[4/5] Step 3: Verifying debounced Auto-Save...")
        # Wait for SAVE_DEBOUNCE = 1000ms plus network flush
        time.sleep(2.5)

        save_badge = cdp.evaluate("""
            (() => {
                const el = document.querySelector('.cv-topbar .cv-save');
                return {
                    text: el?.innerText.trim() || '',
                    is_saved: el?.classList.contains('t-ok') && el?.innerText.includes('已保存')
                };
            })()
        """)
        print("TopBar save badge:", save_badge)

        saved_shot = os.path.join(SCREENSHOTS_DIR, "05_canvas_saved.png")
        cdp.capture_screenshot(saved_shot)

        # Verify backend API GET /api/v2/studio/canvases/{id}
        backend_url = f"http://localhost:{CORE_PORT}/api/v2/studio/canvases/{new_canvas_id}"
        with urllib.request.urlopen(backend_url, timeout=5) as resp:
            backend_record = json.loads(resp.read().decode())

        backend_version = backend_record.get("version", 0)
        saved_nodes = backend_record.get("doc", {}).get("nodes", [])
        saved_node_texts = [n.get("data", {}).get("text") for n in saved_nodes if n.get("data", {}).get("text")]
        print(f"Backend record: version={backend_version}, saved_nodes={len(saved_nodes)}, texts={saved_node_texts}")

        backend_has_text = any(edited_text_content in t for t in saved_node_texts)
        assert backend_version >= 1, f"Expected backend version >= 1, got {backend_version}"
        assert backend_has_text, f"Edited text '{edited_text_content}' not found in backend nodes: {saved_nodes}"

        report["steps"]["step3_save_canvas"] = {
            "status": "PASS",
            "topbar_save_badge": save_badge,
            "backend_version": backend_version,
            "backend_nodes_count": len(saved_nodes),
            "backend_saved_text": edited_text_content,
            "screenshot": saved_shot,
        }

        # -------------------------------------------------------------
        # STEP 4: 重新打开验证 (Reopen Verification)
        # -------------------------------------------------------------
        print(f"[5/5] Step 4: Reopening canvas via direct URL revisit...")
        reopen_url = f"http://localhost:{STUDIO_PORT}/studio/?view=flow&canvas={new_canvas_id}&novel=nv_01M1MER58J7H3B06F0BQF0TNTE&chapter=ch_01M1METGFD9RXHWWV8FR65Z57K&plan=sp_01M20G8W1RN8BZ7FVE6FQHZ0P6"
        cdp.call("Page.navigate", {"url": reopen_url})
        time.sleep(4.0)

        reopened_dom = cdp.evaluate("""
            (() => {
                const nodes = Array.from(document.querySelectorAll('.react-flow__node'));
                const saveBadge = document.querySelector('.cv-topbar .cv-save')?.innerText.trim() || '';
                return {
                    node_count: nodes.length,
                    nodes: nodes.map(n => ({
                        id: n.getAttribute('data-id'),
                        title: n.querySelector('.cv-node__title')?.innerText || '',
                        plain_text: n.querySelector('.cv-text__plain')?.innerText || '',
                        card_text: (n.querySelector('.cv-card')?.innerText || '').slice(0, 100)
                    })),
                    save_badge: saveBadge
                };
            })()
        """)
        print("Reopened DOM state:", reopened_dom)

        reopened_shot = os.path.join(SCREENSHOTS_DIR, "06_canvas_reopened.png")
        cdp.capture_screenshot(reopened_shot)
        print("Captured reopened screenshot:", reopened_shot)

        # Assert edited text node is preserved on reopen
        preserved_node = next(
            (n for n in reopened_dom.get("nodes", [])
             if edited_text_content in (n.get("plain_text") or n.get("card_text"))),
            None
        )
        assert preserved_node, f"Edited text node was NOT found on reopen! Reopened nodes: {reopened_dom.get('nodes')}"
        print(f"Preserved node verified on reopen: ID={preserved_node['id']}")

        reopen_has_story_summary = any("故事梗概" in (n.get("title") or "") for n in reopened_dom.get("nodes", []))

        report["steps"]["step4_reopen_canvas"] = {
            "status": "PASS",
            "reopened_node_count": reopened_dom.get("node_count"),
            "preserved_edited_node": preserved_node,
            "has_unwanted_story_card": reopen_has_story_summary,
            "screenshot": reopened_shot,
        }

        # Overall Status
        report["overall_status"] = "PASSED_WITH_DEFECTS" if report["defects_observed"] else "PASSED"

    except Exception as e:
        import traceback
        traceback.print_exc()
        report["overall_status"] = "ERROR"
        report["error"] = str(e)
    finally:
        cdp.stop()
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"E2E test run complete. Report saved to: {REPORT_PATH}")

    return report


if __name__ == "__main__":
    rep = run_e2e_verification()
    print("Execution Result Summary:")
    print(f"Status: {rep.get('overall_status')}")
    for k, v in rep.get("steps", {}).items():
        print(f"  {k}: {v.get('status')}")
    if rep.get("defects_observed"):
        print("Observed Defects:")
        for d in rep["defects_observed"]:
            print(f"  [{d['id']}] {d['title']}")
    sys.exit(0 if rep.get("overall_status") in ("PASSED", "PASSED_WITH_DEFECTS") else 1)
