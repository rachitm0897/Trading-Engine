import json, os
from datetime import datetime
from pyflink.common import Duration, Time, Types, WatermarkStrategy
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream.functions import ProcessWindowFunction
from pyflink.datastream.state import ValueStateDescriptor
from pyflink.datastream.window import TumblingEventTimeWindows
from jobs.processing import aggregate_bars
from jobs.runtime import environment, sink, source
from jobs.events import envelope


class EventTimestamp(TimestampAssigner):
    def extract_timestamp(self,value,record_timestamp):
        return int(datetime.fromisoformat(value["event_time"].replace("Z","+00:00")).timestamp()*1000)


class BuildBar(ProcessWindowFunction):
    def __init__(self,label,seconds):self.label=label;self.seconds=seconds
    def process(self,key,context,elements):
        ticks=list(elements)
        descriptor=ValueStateDescriptor("bar-correction-version-v1",Types.INT())
        version_state=context.window_state.get_state(descriptor)
        prior=version_state.value() or 0
        bars=aggregate_bars(ticks,self.label,self.seconds)
        if bars:
            bar=bars[0];bar["version"]=prior+1;bar["is_final"]=True;version_state.update(prior+1)
            yield json.dumps(envelope("market.bar","instrument",bar["instrument_id"],bar,
                f"{bar['bar_id']}:{bar['version']}",{},bar["window_end"]),separators=(",",":"))


def main():
    env=environment("bar-aggregation-v1")
    parsed=source(env,"market.canonical.v1","bar-aggregation-v1").map(lambda value:json.loads(value)["payload"]).assign_timestamps_and_watermarks(
        WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(int(os.getenv("ALLOWED_LATENESS_SECONDS","30")))).with_timestamp_assigner(EventTimestamp())).uid("bar-event-time-v1")
    allowed=Time.seconds(int(os.getenv("ALLOWED_LATENESS_SECONDS","30")))
    for label,seconds in [("1m",60),("5m",300),("1d",86400)]:
        bars=parsed.key_by(lambda x:x["instrument_id"]).window(TumblingEventTimeWindows.of(Time.seconds(seconds))).allowed_lateness(allowed).process(
            BuildBar(label,seconds),output_type=Types.STRING()).uid(f"bar-{label}-window-v1")
        sink(bars,"market.bars.v1",f"bar-{label}-sink-v1")
    env.execute("bar-aggregation-v1")


if __name__=="__main__":main()
