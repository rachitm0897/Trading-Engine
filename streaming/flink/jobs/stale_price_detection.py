import json, os
from datetime import datetime, timedelta, timezone
from pyflink.common import Types
from pyflink.datastream.functions import KeyedProcessFunction
from pyflink.datastream.state import ValueStateDescriptor
from jobs.runtime import environment, sink, source
from jobs.events import envelope
from jobs.identity import market_quality_event_key, processing_mode


class StaleTimer(KeyedProcessFunction):
    def open(self,runtime_context):
        self.latest=runtime_context.get_state(ValueStateDescriptor("latest-market-event-v1",Types.STRING()))
        self.timer=runtime_context.get_state(ValueStateDescriptor("stale-processing-timer-v1",Types.LONG()))
        self.delay=int(os.getenv("MARKET_PRICE_STALE_SECONDS","300"))*1000
    def process_element(self,value,ctx):
        source_event=json.loads(value);tick=source_event["payload"];mode=processing_mode(tick.get("processing_mode"))
        canonical_event_id=source_event["event_id"]
        payload={"instrument_id":tick["instrument_id"],"status":"FRESH","reference_price":tick["price"],
            "latest_event_at":tick["event_time"],"source_event_id":canonical_event_id,
            "provider_source_event_id":tick["source_event_id"],"stale_after_seconds":self.delay//1000,
            "provider":tick.get("provider","IBKR"),"source":tick.get("source","ibkr"),
            "provider_generation":tick.get("provider_generation"),"processing_mode":mode}
        yield json.dumps(envelope("market.quality","instrument",tick["instrument_id"],payload,
            market_quality_event_key(canonical_event_id,"FRESH"),source_event,tick["event_time"]),separators=(",",":"))
        if mode!="LIVE":
            return
        old=self.timer.value()
        if old:ctx.timer_service().delete_processing_time_timer(old)
        timer=ctx.timer_service().current_processing_time()+self.delay
        self.latest.update(json.dumps({"source":source_event,"tick":tick},separators=(",",":")));self.timer.update(timer)
        ctx.timer_service().register_processing_time_timer(timer)
    def on_timer(self,timestamp,ctx):
        stored=json.loads(self.latest.value());tick=stored["tick"]
        event_time=datetime.fromisoformat(tick["event_time"].replace("Z","+00:00"))
        payload={"instrument_id":tick["instrument_id"],"status":"STALE","reference_price":tick["price"],
            "latest_event_at":tick["event_time"],"source_event_id":stored["source"]["event_id"],
            "provider_source_event_id":tick["source_event_id"],"stale_after_seconds":self.delay//1000,
            "provider":tick.get("provider","IBKR"),"source":tick.get("source","ibkr"),
            "provider_generation":tick.get("provider_generation"),
            "processing_mode":"LIVE",
            "detected_at":(event_time+timedelta(milliseconds=self.delay)).astimezone(timezone.utc).isoformat()}
        yield json.dumps(envelope("market.quality","instrument",tick["instrument_id"],payload,
            market_quality_event_key(stored["source"]["event_id"],"STALE"),stored["source"],tick["event_time"]),separators=(",",":"))


def main():
    env=environment("stale-price-detection-v1")
    quality=source(env,"market.canonical.v1","stale-price-detection-v1").key_by(
        lambda value:json.loads(value)["payload"]["instrument_id"]).process(StaleTimer(),output_type=Types.STRING()).uid("stale-price-timers-v1")
    sink(quality,"market.quality.v1","stale-quality-sink-v1");env.execute("stale-price-detection-v1")


if __name__=="__main__":main()
