import hashlib
import json
from pyflink.common import Types
from pyflink.datastream.functions import KeyedBroadcastProcessFunction
from pyflink.datastream.state import MapStateDescriptor, ValueStateDescriptor
from jobs.processing import compute_indicator
from jobs.runtime import environment, sink, source
from jobs.events import envelope

REQUIREMENTS=MapStateDescriptor("active-strategy-inputs-v1",Types.STRING(),Types.STRING())


class RegistryIndicators(KeyedBroadcastProcessFunction):
    def open(self,runtime_context):
        self.history=runtime_context.get_state(ValueStateDescriptor("rolling-final-bars-v2",Types.STRING()))
        self.previous={}

    def process_broadcast_element(self,value,ctx):
        event=json.loads(value);payload=event.get("payload",{});state=ctx.get_broadcast_state(REQUIREMENTS)
        for identity_hash in payload.get("removed_requirement_hashes",[]):state.remove(identity_hash)
        for requirement in payload.get("requirements",[]):
            if requirement.get("input_type")!="INDICATOR":continue
            item={**requirement,"instrument_id":str(payload["instrument_id"]),"timeframe":payload["timeframe"]}
            state.put(requirement["identity_hash"],json.dumps(item,separators=(",",":")))

    def process_element(self,value,ctx):
        source_event=json.loads(value);bar=source_event["payload"]
        if not bar.get("is_final",False):return
        history=json.loads(self.history.value() or "[]")
        history=[x for x in history if not (x.get("bar_id")==bar.get("bar_id") and x.get("version")==bar.get("version"))]+[bar]
        history=sorted(history,key=lambda x:x["window_end"])[-10000:];self.history.update(json.dumps(history,separators=(",",":")))
        for identity_hash,encoded in ctx.get_broadcast_state(REQUIREMENTS).items():
            requirement=json.loads(encoded)
            if requirement["instrument_id"]!=str(bar["instrument_id"]) or requirement["timeframe"]!=bar["interval"]:continue
            parameters=requirement.get("parameters",{});name=requirement["name"]
            result=compute_indicator(history,name,parameters);previous=self.previous.get(identity_hash);self.previous[identity_hash]=result
            parameter_hash=hashlib.sha256(json.dumps(parameters,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            role=parameters.get("role");output_name=f"{name}_{role}" if role else name
            if name=="donchian":output_name="donchian_upper" if role=="entry" else "donchian_lower"
            source_key=f"{bar['bar_id']}:{bar['version']}:{name}:{parameter_hash}"
            payload={"instrument_id":bar["instrument_id"],"timeframe":bar["interval"],"indicator":output_name,
                "indicator_version":1,"value":str(result) if result is not None else None,
                "previous_value":str(previous) if previous is not None else None,"event_time":bar["window_end"],
                "parameter_version":1,"parameters":parameters,"parameters_hash":parameter_hash,
                "source_bar_id":bar["bar_id"],"source_bar_version":bar["version"],"is_final":True,"source_key":source_key}
            yield json.dumps(envelope("market.indicator","instrument",bar["instrument_id"],payload,
                source_key,source_event,bar["window_end"]),separators=(",",":"))


def main():
    env=environment("indicator-computation-v2")
    bars=source(env,"market.bars.v1","indicator-computation-v2").key_by(
        lambda value:f"{json.loads(value)['payload']['instrument_id']}:{json.loads(value)['payload']['interval']}")
    registry=source(env,"strategy.inputs.v1","indicator-registry-v1").broadcast(REQUIREMENTS)
    values=bars.connect(registry).process(RegistryIndicators(),output_type=Types.STRING()).uid("registry-indicators-v2")
    sink(values,"market.indicators.v1","indicator-sink-v2");env.execute("indicator-computation-v2")


if __name__=="__main__":main()
