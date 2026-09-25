class ExecutionError(Exception): pass
class BrokerDisconnectedError(ExecutionError): pass
class OrderValidationError(ExecutionError): pass
class InsufficientMarginError(ExecutionError): pass
class DuplicateExecutionError(ExecutionError): pass
