import signal
import threading

from django.core.management.base import BaseCommand

from apps.market_data.realtime import FinnhubRealtimeWorker


class Command(BaseCommand):
    help = "Consume Finnhub WebSocket trades and publish UTC-aligned 5-second fallback bars"

    def handle(self, *args, **options):
        stop_event = threading.Event()

        def stop(*_args):
            stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        FinnhubRealtimeWorker(stop_event=stop_event).run_forever()
