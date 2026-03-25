from src.desktop_use.types import UIElement, UIZone, UIBlueprint


class TestUIElement:
    def test_fields(self):
        e = UIElement(name="search", rect=(10, 20, 100, 50),
                      element_type="input", action="click+type",
                      text="搜索", source="win32", confidence=1.0)
        assert e.name == "search"
        assert e.rect == (10, 20, 100, 50)
        assert e.source == "win32"

    def test_center(self):
        e = UIElement(name="btn", rect=(100, 200, 160, 230),
                      element_type="button", action="click",
                      text="OK", source="ocr", confidence=0.95)
        cx = (100 + 160) // 2
        cy = (200 + 230) // 2
        assert e.center == (cx, cy)

    def test_width_height(self):
        e = UIElement(name="x", rect=(10, 20, 110, 70),
                      element_type="label", action="display",
                      text="", source="cv", confidence=0.8)
        assert e.width == 100
        assert e.height == 50


class TestUIZone:
    def test_fields(self):
        z = UIZone(name="chat", rect=(460, 100, 1020, 1500),
                   zone_type="messages", dynamic=True)
        assert z.dynamic is True
        assert z.width == 560


class TestUIBlueprint:
    def test_find_element(self):
        e1 = UIElement("search", (10, 20, 100, 50), "input", "click+type", "搜索", "ocr", 0.9)
        e2 = UIElement("send", (800, 900, 850, 930), "button", "click", "发送", "ocr", 0.95)
        bp = UIBlueprint(window_class="TestClass", window_size=(1024, 768),
                         elements=[e1, e2], zones=[],
                         perception_layers=["ocr"], created_at=0.0)
        assert bp.find("搜索") == e1
        assert bp.find("发送") == e2
        assert bp.find("不存在") is None

    def test_find_zone(self):
        z = UIZone("chat", (460, 100, 1020, 1500), "messages", True)
        bp = UIBlueprint("Test", (1024, 768), [], [z], ["cv"], 0.0)
        assert bp.zone("chat") == z
        assert bp.zone("nope") is None
