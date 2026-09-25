class BrokerReconciler:
    @staticmethod
    def reconcile(database_positions: list, broker_positions: list) -> bool:
        db_count = len(database_positions)
        broker_count = len(broker_positions)
        return db_count == broker_count
