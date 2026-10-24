"""Structural validation for model commands and field-boundary normalization."""


FIELD_X_LIMIT = 50.0
FIELD_Y_LIMIT = 30.0


def enforce_command_constraints(
    commands: list[dict],
    game_state: dict,
    team_id: int,
    player_id: int,
    position_label: str,
    logger=None,
) -> tuple[list[dict], list[str]]:
    """Keep the response shape valid without replacing tactical decisions."""
    if len(commands) != 1:
        return [], ["expected exactly one command"]

    command = commands[0]
    if not isinstance(command, dict):
        return [], ["command must be an object"]

    if not isinstance(command.get("commandType"), str):
        return [], ["commandType must be a string"]

    parameters = command.get("parameters", {})
    if not isinstance(parameters, dict):
        return [], ["command parameters must be an object"]

    if command["commandType"] == "MOVE_TO":
        for key, limit in (("target_x", FIELD_X_LIMIT), ("target_y", FIELD_Y_LIMIT)):
            value = parameters.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                parameters[key] = max(-limit, min(limit, value))

    return commands, []
