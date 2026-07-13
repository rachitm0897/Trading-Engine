import json
import os
from datetime import datetime
from pyflink.common import Duration, Types, WatermarkStrategy
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream.functions import KeyedBroadcastProcessFunction
from pyflink.datastream.state import MapStateDescriptor, ValueStateDescriptor
from jobs.processing import aggregate_bars
from jobs.runtime import environment, sink, source
from jobs.events import envelope

REQUIREMENTS=MapStateDescriptor("active-bar-inputs-v1",Types.STRING(),Types.STRING())


def timeframe_seconds(value):
    value=str(value).strip().lower();units={"s":1,"m":60,"h":3600,"d":86400}
    if len(value)<2 or value[-1] not in units or not value[:-1].isdigit():raise ValueError(f"Unsupported timeframe {value}")
    seconds=int(value[:-1])*units[value[-1]]
    if seconds<=0:raise ValueError("Timeframe must be positive")
    return seconds


class EnvelopeTimestamp(TimestampAssigner):
    def extract_timestamp(self,value,record_timestamp):
        payload=json.loads(value)["payload"]
        return int(datetime.fromisoformat(payload["event_time"].replace("Z","+00:00")).timestamp()*1000)


class RegistryBars(KeyedBroadcastProcessFunction):
    def open(self,runtime_context):
        self.buckets=runtime_context.get_state(ValueStateDescriptor("dynamic-bar-buckets-v1",Types.STRING()))

    def process_broadcast_element(self,value,ctx):
        event=json.loads(value);payload=event.get("payload",{});state=ctx.get_broadcast_state(REQUIREMENTS)
        for identity_hash in payload.get("removed_requirement_hashes",[]):state.remove(identity_hash)
        for requirement in payload.get("requirements",[]):
            if requirement.get("input_type")!="BAR":continue
            item={**requirement,"instrument_id":str(payload["instrument_id"]),"timeframe":payload["timeframe"]}
            state.put(requirement["identity_hash"],json.dumps(item,separators=(",",":")))

    def process_element(self,value,ctx):
        source_event=json.loads(value);tick=source_event["payload"];stored=json.loads(self.buckets.value() or "{}")
        stamp=int(datetime.fromisoformat(tick["event_time"].replace("Z","+00:00")).timestamp())
        for identity_hash,encoded in ctx.get_broadcast_state(REQUIREMENTS).items():
            requirement=json.loads(encoded)
            if requirement["instrument_id"]!=str(tick["instrument_id"]):continue
            seconds=timeframe_seconds(requirement["timeframe"]);start=stamp-stamp%seconds
            key=f"{identity_hash}:{start}";bucket=stored.get(key,{"ticks":[],"version":0,"timeframe":requirement["timeframe"],"seconds":seconds,"end":start+seconds})
            bucket["ticks"]=[x for x in bucket["ticks"] if x["source_event_id"]!=tick["source_event_id"]]+[tick];stored[key]=bucket
            ctx.timer_service().register_event_time_timer((start+seconds)*1000)
        self.buckets.update(json.dumps(stored,separators=(",",":")))

    def on_timer(self,timestamp,ctx):
        stored=json.loads(self.buckets.value() or "{}")
        for key,bucket in list(stored.items()):
            if bucket["end"]*1000!=timestamp:continue
            bucket["version"]+=1
            bars=aggregate_bars(bucket["ticks"],bucket["timeframe"],bucket["seconds"],final=True)
            if bars:
                bar=bars[0];bar["version"]=bucket["version"];bar["is_final"]=True
                source_event={"event_id":bar["bar_id"],"payload":bucket["ticks"][-1]}
                yield json.dumps(envelope("market.bar","instrument",bar["instrument_id"],bar,
                    f"{bar['bar_id']}:{bar['version']}",source_event,bar["window_end"]),separators=(",",":"))
            stored[key]=bucket
        self.buckets.update(json.dumps(stored,separators=(",",":")))


def main():
    env=environment("bar-aggregation-v2")
    ticks=source(env,"market.canonical.v1","bar-aggregation-v2").assign_timestamps_and_watermarks(
        WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(int(os.getenv("ALLOWED_LATENESS_SECONDS","30")))).with_timestamp_assigner(EnvelopeTimestamp())).key_by(
        lambda value:str(json.loads(value)["payload"]["instrument_id"]))
    registry=source(env,"strategy.inputs.v1","bar-registry-v1").broadcast(REQUIREMENTS)
    bars=ticks.connect(registry).process(RegistryBars(),output_type=Types.STRING()).uid("registry-bars-v2")
    sink(bars,"market.bars.v1","bar-sink-v2");env.execute("bar-aggregation-v2")


if __name__=="__main__":main()
