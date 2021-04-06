# Standard Library
import asyncio
import logging
import os
import signal

# Third Party
import pandas as pd
from nats.aio.client import Client as NATS

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class NatsWrapper:
    def __init__(self):
        self.nc = NATS()
        self.NATS_SERVER_URL = os.environ["NATS_SERVER_URL"]

    async def connect(self, loop):
        async def error_cb(e):
            logging.warning("Error: {}".format(str(e)))

        async def closed_cb():
            logging.warning("Closed connection to NATS")
            await asyncio.sleep(0.1, loop=loop)
            loop.stop()

        async def on_disconnect():
            logging.warning("Disconnected from NATS")

        async def reconnected_cb():
            logging.warning(
                "Reconnected to NATS at nats://{}".format(self.nc.connected_url.netloc)
            )

        options = {
            "loop": loop,
            "error_cb": error_cb,
            "closed_cb": closed_cb,
            "reconnected_cb": reconnected_cb,
            "disconnected_cb": on_disconnect,
            "servers": [self.NATS_SERVER_URL],
        }

        try:
            await self.nc.connect(**options)
        except Exception as e:
            logging.error(e)

        logging.info(f"Connected to NATS at {self.nc.connected_url.netloc}...")

    def add_signal_handler(self, loop):
        def signal_handler():
            if self.nc.is_closed:
                return
            logging.warning("Disconnecting...")
            loop.create_task(self.nc.close())

        for sig in ("SIGINT", "SIGTERM"):
            loop.add_signal_handler(getattr(signal, sig), signal_handler)

    async def subscribe(
        self,
        nats_subject: str,
        payload_queue: asyncio.Queue,
        nats_queue: str = "",
        subscribe_handler=None,
    ):
        async def default_subscribe_handler(msg):
            subject = msg.subject
            reply = msg.reply
            payload_data = msg.data.decode()
            await payload_queue.put(payload_data)

        if subscribe_handler is None:
            subscribe_handler = default_subscribe_handler
        await self.nc.subscribe(nats_subject, queue=nats_queue, cb=subscribe_handler)

    async def publish(self, nats_subject: str, payload_df):
        """
        this is not necessary at this point though
        """
        await self.nc.publish(nats_subject, payload_df)


#####################################################################
##                          example usage:                         ##
#####################################################################


async def nats_subscriber(nw, loop, payload_queue):
    await nw.connect(loop)
    nw.add_signal_handler(loop)
    await nw.subscribe(nats_subject="logs", payload_queue=payload_queue)


async def nats_publisher(nw, payload_queue):
    while True:
        payload = await payload_queue.get()
        if payload is None:
            continue
        payload_df = pd.read_json(payload, dtype={"_id": object})
        await nw.publish("preprocessed_logs", payload_df.to_json().encode())


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    payload_queue = asyncio.Queue(loop=loop)

    nw = NatsWrapper()
    subscriber_coroutine = nats_subscriber(nw, loop, payload_queue)
    publisher_coroutine = nats_publisher(nw, payload_queue)

    loop.run_until_complete(asyncio.gather(subscriber_coroutine, publisher_coroutine))
    try:
        loop.run_forever()
    finally:
        loop.close()