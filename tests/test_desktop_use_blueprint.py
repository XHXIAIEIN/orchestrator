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


from src.desktop_use.blueprint import BlueprintBuilder
from src.desktop_use.perception import PerceptionLayer, PerceptionResult


class FakeLayer(PerceptionLayer):
    def __init__(self, result):
        self._result = result
    def analyze(self, hwnd, rect):
        return self._result


class TestBlueprintBuilder:
    def test_builds_from_single_layer(self):
        layer = FakeLayer(PerceptionResult(
            elements=[UIElement("btn", (10, 20, 60, 40), "button", "click", "OK", "test", 1.0)],
            zones=[UIZone("main", (0, 0, 800, 600), "panel", False)],
            needs_fallback=False,
            layer_name="test",
        ))
        builder = BlueprintBuilder(layers=[layer])
        bp = builder.build(hwnd=0, window_class="Test", rect=(0, 0, 800, 600))
        assert isinstance(bp, UIBlueprint)
        assert len(bp.elements) == 1
        assert len(bp.zones) == 1

    def test_fallback_chain(self):
        layer1 = FakeLayer(PerceptionResult(
            elements=[], needs_fallback=True, layer_name="layer1",
        ))
        layer2 = FakeLayer(PerceptionResult(
            elements=[UIElement("x", (0,0,10,10), "text", "display", "X", "l2", 1.0)],
            zones=[UIZone("z", (0,0,100,100), "panel", False)],
            needs_fallback=False, layer_name="layer2",
        ))
        builder = BlueprintBuilder(layers=[layer1, layer2])
        bp = builder.build(hwnd=0, window_class="Test", rect=(0, 0, 100, 100))
        assert len(bp.elements) == 1
        assert "layer1" in bp.perception_layers
        assert "layer2" in bp.perception_layers

    def test_cache_hit(self):
        call_count = [0]
        class CountingLayer(PerceptionLayer):
            def analyze(self, hwnd, rect):
                call_count[0] += 1
                return PerceptionResult(
                    elements=[UIElement("a", (0,0,1,1), "label", "display", "A", "t", 1.0)],
                    needs_fallback=False, layer_name="counting",
                )
        builder = BlueprintBuilder(layers=[CountingLayer()])
        bp1 = builder.build(hwnd=0, window_class="C", rect=(0, 0, 800, 600))
        bp2 = builder.build(hwnd=0, window_class="C", rect=(0, 0, 800, 600))
        assert call_count[0] == 1
        assert bp1 is bp2

    def test_cache_invalidate_on_resize(self):
        call_count = [0]
        class CountingLayer(PerceptionLayer):
            def analyze(self, hwnd, rect):
                call_count[0] += 1
                return PerceptionResult(
                    elements=[], needs_fallback=False, layer_name="counting",
                )
        builder = BlueprintBuilder(layers=[CountingLayer()])
        builder.build(hwnd=0, window_class="C", rect=(0, 0, 800, 600))
        builder.build(hwnd=0, window_class="C", rect=(0, 0, 1024, 768))
        assert call_count[0] == 2

    def test_invalidate_by_class(self):
        class SimpleLayer(PerceptionLayer):
            def analyze(self, hwnd, rect):
                return PerceptionResult(needs_fallback=False, layer_name="simple")
        builder = BlueprintBuilder(layers=[SimpleLayer()])
        builder.build(hwnd=0, window_class="A", rect=(0,0,100,100))
        builder.build(hwnd=0, window_class="B", rect=(0,0,100,100))
        assert len(builder._cache) == 2
        builder.invalidate("A")
        assert len(builder._cache) == 1
        builder.invalidate()
        assert len(builder._cache) == 0
