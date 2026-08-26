# Freeze the Data Generation at ResearchRun admission

ResearchRun admission freezes and retains the current validated Data Generation before queueing, and every Attempt uses that same Generation through success, failure, or cancellation. Queue delay, retry, Worker loss, and concurrent Refresh therefore cannot change the accepted research question.
