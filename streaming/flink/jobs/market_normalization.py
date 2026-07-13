import hashlib, json
from pyflink.common import Types
from pyflink.datastream.functions import KeyedBroadcastProcessFunction, KeyedProcessFunction
from pyflink.datastream.output_tag import OutputTag
from pyflink.datastream.state import MapStateDescriptor, ValueStateDescriptor
from jobs.processing import normalize_market_event
from jobs.runtime import environment, sink, source
from jobs.events import envelope, payload_of

DLQ = OutputTag("normalization-dead-letter-v1", Types.STRING())
REGISTRY=MapStateDescriptor("instrument-registry-by-conid-v1",Types.STRING(),Types.STRING())


class Validate(KeyedBroadcastProcessFunction):
    def process_broadcast_element(self,value,ctx):
        event=json.loads(value);payload=event.get("payload",{});conid=payload.get("conid")
        if conid is None:return
        state=ctx.get_broadcast_state(REGISTRY)
        if payload.get("active",True):state.put(str(conid),json.dumps(payload,separators=(",",":")))
        else:state.remove(str(conid))
    def process_element(self, value, ctx):
        try:
            incoming=json.loads(value);raw=payload_of(incoming);encoded=ctx.get_broadcast_state(REGISTRY).get(str(raw.get("conid")))
            if not encoded:raise ValueError(f"unknown conId {raw.get('conid')}; instrument registry has no active mapping")
            registered=json.loads(encoded);canonical=normalize_market_event({**raw,"instrument_id":registered["instrument_id"]},{})
            yield json.dumps(envelope("market.canonical","instrument",canonical["instrument_id"],canonical,
                canonical["source_event_id"],incoming,canonical["event_time"]),separators=(",",":"))
        except Exception as exc:
            payload={"source_topic":"market.raw.v1","reason":str(exc),"raw":value}
            ctx.output(DLQ,json.dumps(envelope("dead-letter","stream","market.raw.v1",payload,
                hashlib.sha256(value.encode()).hexdigest(),{}),separators=(",",":")))


class Deduplicate(KeyedProcessFunction):
    def open(self, runtime_context):
        self.seen=runtime_context.get_state(ValueStateDescriptor("seen-source-event-v1",Types.BOOLEAN()))
    def process_element(self,value,ctx):
        if not self.seen.value():
            self.seen.update(True);yield value


def main():
    env=environment("market-normalization-v1")
    raw=source(env,"market.raw.v1","market-normalization-v1").key_by(lambda value:str(payload_of(json.loads(value)).get("conid")))
    registry=source(env,"instrument.registry.v1","instrument-registry-v1").broadcast(REGISTRY)
    checked=raw.connect(registry).process(Validate(),output_type=Types.STRING()).uid("market-normalization-validate-v2")
    canonical=checked.key_by(lambda value:json.loads(value)["payload"]["source_event_id"]).process(Deduplicate(),output_type=Types.STRING()).uid("market-normalization-deduplicate-v1")
    sink(canonical,"market.canonical.v1","market-normalization-canonical-sink-v1")
    sink(checked.get_side_output(DLQ),"dead-letter.v1","market-normalization-dlq-sink-v1")
    env.execute("market-normalization-v1")


if __name__=="__main__":main()
