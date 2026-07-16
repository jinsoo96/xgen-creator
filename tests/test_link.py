import tempfile
import unittest
from pathlib import Path

from xgen_creator.link import route_from_rel, scan_routes, resolve_element
from xgen_creator.link.routes_nextjs import match_route
from xgen_creator.bridge.driver import resolve_goto


class ResolveGotoTest(unittest.TestCase):
    BASE = "http://localhost:3100"

    def test_app_path_resolved(self):
        self.assertEqual(resolve_goto("/canvas", self.BASE), "http://localhost:3100/canvas")

    def test_none_defaults_root(self):
        self.assertEqual(resolve_goto(None, self.BASE), "http://localhost:3100/")

    def test_same_origin_http_kept(self):
        self.assertEqual(resolve_goto("http://localhost:3100/x", self.BASE),
                         "http://localhost:3100/x")

    def test_invalid_and_offsite_rejected(self):
        for bad in ("about:blank", "address-bar", "https://evil.com/", "javascript:1"):
            self.assertIsNone(resolve_goto(bad, self.BASE), bad)


class RouteMapTest(unittest.TestCase):
    def test_route_from_rel(self):
        cases = {
            "apps/web/src/app/(main)/dashboard/page.tsx": "/dashboard",
            "apps/web/src/app/page.tsx": "/",
            "app/chat/[id]/page.tsx": "/chat/[id]",
            "src/components/button.tsx": None,
        }
        for rel, expected in cases.items():
            self.assertEqual(route_from_rel(rel), expected, rel)

    def test_scan_routes_skips_build_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "apps/web/app/dashboard").mkdir(parents=True)
            (root / "apps/web/app/dashboard/page.tsx").write_text("export default 1")
            (root / "node_modules/pkg/app/evil").mkdir(parents=True)
            (root / "node_modules/pkg/app/evil/page.tsx").write_text("x")
            routes = scan_routes(root)
            self.assertEqual(list(routes), ["/dashboard"])

    def test_match_route_with_param(self):
        routes = {"/chat/[id]": "app/chat/[id]/page.tsx", "/": "app/page.tsx"}
        self.assertEqual(match_route(routes, "/chat/42"),
                         ("/chat/[id]", "app/chat/[id]/page.tsx"))
        self.assertEqual(match_route(routes, "/"), ("/", "app/page.tsx"))
        self.assertIsNone(match_route(routes, "/missing/deep"))


class ElementResolverTest(unittest.TestCase):
    def test_testid_beats_class_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "features/run").mkdir(parents=True)
            (root / "features/run/run-button.tsx").write_text(
                'export const RunButton = () => (\n'
                '  <button data-testid="run-button" className="primary-action">실행</button>\n'
                ');\n', encoding="utf-8")
            (root / "features/run/other.tsx").write_text(
                '<div className="primary-action">기타</div>', encoding="utf-8")

            element = {"tag": "button", "testid": "run-button",
                       "classes": ["primary-action"], "text": "실행"}
            found = resolve_element(element, [str(root)])
            self.assertTrue(found)
            self.assertEqual(found[0]["score"], 100)
            self.assertTrue(found[0]["file"].endswith("run-button.tsx"))
            self.assertEqual(found[0]["line"], 2)

    def test_no_evidence_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_element({"tag": "div"}, [tmp]), [])


if __name__ == "__main__":
    unittest.main()
