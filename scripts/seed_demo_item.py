"""Give a fresh hub its starting item (config/demo_item.json): a label, then where it sits. Run by scripts/session.sh."""
import asyncio
import json
import pathlib
import time

from earmark_contracts import Label, PlaceItem
from earmark_hub.client import BusClient

ROOT = pathlib.Path(__file__).resolve().parent.parent


async def main() -> None:
    item = json.loads((ROOT / "config" / "demo_item.json").read_text())
    if not item.get("position"):
        return
    client = await BusClient.connect("cli", url="ws://127.0.0.1:8765")
    await client.send(Label(tag=f"VOICE-{item['name']}", name=item["name"], aliases=item.get("aliases", []), spot=None))
    await asyncio.sleep(0.3)  # the hub adds the item before it can be placed
    object_id = "_".join(item["name"].lower().split())
    await client.send(PlaceItem(object_id=object_id, position=item["position"], t=time.time()))
    await asyncio.sleep(0.3)
    await client.close()
    print(f"starting item: {item['name']} at {item['position']}")


asyncio.run(main())
