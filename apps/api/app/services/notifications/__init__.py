"""Notification dispatch (brief Section 34/45): a pluggable NotificationChannel
abstraction (mirroring app/services/exchanges' ExchangeAdapter pattern) plus a
NotificationService that fans one event out to every configured channel and
persists an `alerts` row per attempt, whether or not delivery succeeded.
"""
