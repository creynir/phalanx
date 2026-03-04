"""Phalanx adaptive control skills.

Skills implement the 3-loop adaptive control system:
- FailureEscalator: routes worker failures through retry → team_lead → engineering_manager
- TeamLead (Middle Loop): handles step failures with structured strategies
- EngineeringManager (Outer Loop): handles systemic infrastructure issues
- CheckpointManager: persists step-level checkpoints for resumable skill runs
"""
