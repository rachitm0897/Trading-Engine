import json
from pyflink.common import Types
from pyflink.datastream.functions import KeyedProcessFunction
from pyflink.datastream.state import ValueStateDescriptor
from jobs.processing import compute_indicators
from jobs.runtime import environment, sink, source
from jobs.events import envelope


class RollingIndicators(KeyedProcessFunction):
    def open(self,runtime_context):
        self.history=runtime_context.get_state(ValueStateDescriptor("rolling-final-bars-v1",Types.STRING()))
    def process_element(self,value,ctx):
        source_event=json.loads(value);bar=source_event["payload"]
        if not bar.get("is_final",False):return
        history=json.loads(self.history.value() or "[]")
        history=[x for x in history if x.get("bar_id")!=bar.get("bar_id")]+[bar]
        history=sorted(history,key=lambda x:x["window_end"])[-252:]
        self.history.update(json.dumps(history,separators=(",",":")))
        parameters={"fast":20,"slow":50,"rsi":14,"donchian":20,"momentum":20,"volatility":20,"adv":20}
        for name,result in compute_indicators(history).items():
            payload={"instrument_id":bar["instrument_id"],"indicator":name,
                "value":str(result) if result is not None else None,"event_time":bar["window_end"],
                "parameter_version":1,"parameters":parameters,
                "source_key":f"{bar['bar_id']}:{bar['version']}:{name}"}
            yield json.dumps(envelope("market.indicator","instrument",bar["instrument_id"],payload,
                payload["source_key"],source_event,bar["window_end"]),separators=(",",":"))


def main():
    env=environment("indicator-computation-v1")
    values=source(env,"market.bars.v1","indicator-computation-v1").key_by(
        lambda value:json.loads(value)["payload"]["instrument_id"]).process(RollingIndicators(),output_type=Types.STRING()).uid("rolling-indicators-v1")
    sink(values,"market.indicators.v1","indicator-sink-v1");env.execute("indicator-computation-v1")


if __name__=="__main__":main()
