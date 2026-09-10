"""Unit tests for globally shared shed-capacity reservation in OrderBuilder."""
import pytest
from market.order_builder import OrderBuilder


class DummyTile:
    def __init__(self, x, y, kind="EMPTY", is_animal=False, animal=None):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_animal = is_animal
        self.animal = animal


class DummyPrivate:
    def __init__(self, shed=None):
        self.shed = shed or {}
        self.seeds = {}
        self.inventories = []


class DummyFarm:
    def __init__(self, tiles, money=100000):
        self.tiles = tiles
        self.money = money
        self.hands = []
        self.unlocked = {"NW", "NE", "SW"}
        self.hires_today = 0

    def iter_tiles(self):
        return iter(self.tiles)


class DummyMarket:
    def __init__(self, inventory=None):
        self.inventory = inventory or {"WHEAT": 10000}


def test_multi_species_shared_shed_room_limit():
    """If shed only has room for 3 items, animal buys across species cannot exceed 3 total."""
    # 97 items in shed -> 3 remaining room
    private = DummyPrivate(shed={"MILK": 97})
    # 5 empty pastures, 5 empty coops
    tiles = [DummyTile(0, i, kind="PASTURE") for i in range(5)] + [DummyTile(1, i, kind="COOP") for i in range(5)]
    farm = DummyFarm(tiles, money=50000)
    market = DummyMarket()
    ctx = {"farm": farm, "private": private, "market": market}

    builder = OrderBuilder(money_reserve=0)
    intents = {
        "buy_animal": {"COW": 2, "SHEEP": 2, "GOOSE": 2},
    }
    orders, ledger = builder.build(ctx, intents)

    # Total animals bought cannot exceed remaining room (3)
    anim_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
    total_bought = sum(o[2] for o in anim_orders)
    assert total_bought == 3, f"Expected 3 animals bought due to shed room 3, got {total_bought}"
    
    # Check dropped reasons
    shed_full_drops = [d for d in ledger["dropped"] if d.get("reason") == "shed_full"]
    assert len(shed_full_drops) > 0


def test_full_shed_blocks_all_animals():
    """If shed is at 100 items, 0 animals can be bought, all dropped with shed_full."""
    private = DummyPrivate(shed={"MILK": 100})
    tiles = [DummyTile(0, i, kind="PASTURE") for i in range(5)]
    farm = DummyFarm(tiles, money=50000)
    market = DummyMarket()
    ctx = {"farm": farm, "private": private, "market": market}

    builder = OrderBuilder(money_reserve=0)
    intents = {"buy_animal": {"COW": 2}}
    orders, ledger = builder.build(ctx, intents)

    anim_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert len(anim_orders) == 0
    assert any(d.get("kind") == "animal" and d.get("reason") == "shed_full" for d in ledger["dropped"])


def test_wheat_buy_decrements_shed_room_for_animals():
    """BUY_PRODUCT wheat consumes shed room before animal purchases."""
    # 95 items in shed -> 5 room
    private = DummyPrivate(shed={"WOOL": 95})
    tiles = [DummyTile(0, i, kind="PASTURE") for i in range(5)]
    farm = DummyFarm(tiles, money=50000)
    market = DummyMarket()
    ctx = {"farm": farm, "private": private, "market": market}

    builder = OrderBuilder(money_reserve=0)
    # Want 3 wheat + 4 cows
    intents = {
        "buy_wheat": 3,
        "buy_animal": {"COW": 4},
    }
    orders, ledger = builder.build(ctx, intents)

    # 3 wheat should be bought (consumes 3 shed room -> 2 remaining)
    wheat_orders = [o for o in orders if o[0] == "BUY_PRODUCT"]
    assert sum(o[2] for o in wheat_orders) == 3

    # Only 2 cows can fit
    cow_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert sum(o[2] for o in cow_orders) == 2
