from celery import shared_task
from django.conf import settings
from django.utils import timezone
from .models import StreamHealthMetric
from .services import publish_batch


@shared_task
def publish_outbox_events():
    return publish_batch()


@shared_task
def check_stream_health():
    status, value = "DISABLED", {"enabled": False}
    if settings.KAFKA_ENABLED:
        try:
            from confluent_kafka.admin import AdminClient
            metadata = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS}).list_topics(timeout=5)
            status, value = "HEALTHY", {"enabled": True, "topics": len(metadata.topics)}
        except Exception as exc:
            status, value = "DEGRADED", {"enabled": True, "error": str(exc)[:255]}
    metric, _ = StreamHealthMetric.objects.update_or_create(component="kafka", metric="connectivity",
                                                              defaults={"status": status, "value": value})
    lag_status="DISABLED";lag_value={"topics":{},"total":0}
    if settings.KAFKA_ENABLED and status=="HEALTHY":
        consumer=None
        try:
            from confluent_kafka import Consumer, TopicPartition
            topics=["market.bars.v1","market.indicators.v1","market.quality.v1"]
            consumer=Consumer({"bootstrap.servers":settings.KAFKA_BOOTSTRAP_SERVERS,
                "group.id":"finflock-backend-market-persistence-v1","enable.auto.commit":False})
            partitions=[]
            topic_partitions={}
            cluster=consumer.list_topics(timeout=5)
            for topic in topics:
                ids=sorted((cluster.topics.get(topic).partitions if cluster.topics.get(topic) else {}).keys())
                topic_partitions[topic]=[TopicPartition(topic,partition) for partition in ids]
                partitions.extend(topic_partitions[topic])
            committed={(item.topic,item.partition):item.offset for item in consumer.committed(partitions,timeout=5)} if partitions else {}
            for topic,items in topic_partitions.items():
                total=0
                for item in items:
                    _,high=consumer.get_watermark_offsets(item,timeout=5,cached=False)
                    offset=committed.get((item.topic,item.partition),-1)
                    total+=high if offset is None or offset<0 else max(0,high-offset)
                lag_value["topics"][topic]=total;lag_value["total"]+=total
            lag_status="DEGRADED" if lag_value["total"]>settings.KAFKA_LAG_DEGRADED_THRESHOLD else "HEALTHY"
        except Exception as exc:
            lag_status="DEGRADED";lag_value={"topics":{},"total":None,"error":str(exc)[:255]}
        finally:
            if consumer:consumer.close()
    StreamHealthMetric.objects.update_or_create(component="backend-market-consumer",metric="topic_lag",
        defaults={"status":lag_status,"value":lag_value})
    gateway_status="DEGRADED";gateway_value={"connected":False,"reconciled":False}
    try:
        from apps.broker_gateway.client import GatewayClient
        gateway_value=GatewayClient().health() or gateway_value
        gateway_status="HEALTHY" if gateway_value.get("connected") and gateway_value.get("reconciled") else "DEGRADED"
    except Exception as exc:
        gateway_value={**gateway_value,"error":str(exc)[:255]}
    StreamHealthMetric.objects.update_or_create(component="gateway",metric="connectivity",
        defaults={"status":gateway_status,"value":gateway_value})
    return {"status":metric.status,"lag_status":lag_status,"gateway_status":gateway_status,
        "observed_at":timezone.now().isoformat()}


@shared_task
def execute_replay_request(request_id):
    from .services import execute_replay
    return execute_replay(request_id)
