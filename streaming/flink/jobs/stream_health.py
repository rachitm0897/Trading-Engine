import os
from datetime import datetime, timezone
import json
from pyflink.common import Types
from jobs.runtime import environment, sink, source
from jobs.events import envelope


def main():
    env=environment("stream-health-v1")
    def health(value):
        source_event=json.loads(value);payload={"component":"flink","status":source_event["payload"].get("status","UNKNOWN"),"observed_at":datetime.now(timezone.utc).isoformat()}
        return json.dumps(envelope("system.health","system","flink",payload,source_event["event_id"],source_event),separators=(",",":"))
    values=source(env,"market.quality.v1","stream-health-v1").map(health,output_type=Types.STRING()).uid("stream-health-map-v1")
    sink(values,"system.health.v1","stream-health-sink-v1");env.execute("stream-health-v1")


if __name__ == "__main__": main()
