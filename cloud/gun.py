# 并行工作进程数
workers = 1
# 指定每个工作者的线程数
threads = 2
# 监听端口
bind = '0.0.0.0:5001'
# 工作模式
worker_class = 'gevent'
# 请求超时时间
timeout = 60
# 最大并发量
worker_connections = 100
# 日志配置（输出到 stdout/stderr）
accesslog = '-'
errorlog = '-'
loglevel = 'info'

