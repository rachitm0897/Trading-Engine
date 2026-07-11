import json
import signal
from django.conf import settings
from django.core.management.base import BaseCommand
from apps.event_bus.services import route_dead_letter
from apps.market_streams.services import consume_market_event


class Command(BaseCommand):
    help="Persist Flink market outputs idempotently and commit offsets only after PostgreSQL commits."

    def add_arguments(self,parser):
        parser.add_argument("--once",action="store_true")

    def handle(self,*args,**options):
        if not settings.KAFKA_ENABLED:
            self.stdout.write("Kafka is disabled; market consumer exiting")
            return
        from confluent_kafka import Consumer
        consumer=Consumer({"bootstrap.servers":settings.KAFKA_BOOTSTRAP_SERVERS,
            "group.id":"finflock-backend-market-persistence-v1","enable.auto.commit":False,
            "auto.offset.reset":"earliest"})
        consumer.subscribe(["market.bars.v1","market.indicators.v1","market.quality.v1"])
        running=True
        def stop(*_args):
            nonlocal running;running=False
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        try:
            while running:
                message=consumer.poll(1)
                if message is None:
                    if options["once"]:break
                    continue
                if message.error():
                    raise RuntimeError(str(message.error()))
                try:
                    envelope=json.loads(message.value())
                    consume_market_event("market-persistence-v1",envelope)
                except Exception as exc:
                    route_dead_letter(message.topic(),envelope if "envelope" in locals() else {"raw":message.value().decode(errors="replace")},exc,"market-persistence-v1")
                consumer.commit(message=message,asynchronous=False)
                if options["once"]:break
        finally:
            consumer.close()
