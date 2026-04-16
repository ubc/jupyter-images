from ngshare_exchange import configureExchange

c = get_config()
configureExchange(
    c, 'http://ngshare.default.svc.cluster.local:8080/jupyter/services/ngshare'
)
