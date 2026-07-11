import hashlib, json, os
from pyflink.common import Types
from pyflink.datastream.functions import KeyedProcessFunction, ProcessFunction
from pyflink.datastream.output_tag import OutputTag
from pyflink.datastream.state import ValueStateDescriptor
from jobs.processing import normalize_market_event
from jobs.runtime import environment, sink, source
from jobs.events import envelope, payload_of

DLQ = OutputTag("normalization-dead-letter-v1", Types.STRING())


class Validate(ProcessFunction):
    def __init__(self, symbols): self.symbols=symbols
    def process_element(self, value, ctx):
        try:
            incoming=json.loads(value);canonical=normalize_market_event(payload_of(incoming),self.symbols)
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
    checked=source(env,"market.raw.v1","market-normalization-v1").process(Validate(json.loads(os.getenv("INSTRUMENT_SYMBOL_MAP","{}"))),output_type=Types.STRING()).uid("market-normalization-validate-v1")
    canonical=checked.key_by(lambda value:json.loads(value)["payload"]["source_event_id"]).process(Deduplicate(),output_type=Types.STRING()).uid("market-normalization-deduplicate-v1")
    sink(canonical,"market.canonical.v1","market-normalization-canonical-sink-v1")
    sink(checked.get_side_output(DLQ),"dead-letter.v1","market-normalization-dlq-sink-v1")
    env.execute("market-normalization-v1")


if __name__=="__main__":main()
