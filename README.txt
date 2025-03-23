Ad-hoc/hacky tooling to replicate ClaudePlaysPokemon, except with Pokémon Yellow and Gemini or OpenAI models.

(They don't do very well.)

Not well-documented aside from this readme, nor configurable, so be prepared to edit the code.

What is supported:
- Controlling the game.
- Overlaying grid coordinates on screenshots in a similar way to ClaudePlaysPokemon.
    - There's a bug where coordinates show up on the intro cutscene, but it doesn't affect anything.

What is not supported:
- Navigator tool (felt like cheating).
    - Instead it can only press one button at a time (I tried letting it use a sequence of buttons but it tended to get messed up).
- Memories.
    - I didn't get that far as implementing this because the AI got stuck before getting far enough in the game for this to be useful.


How to use:

- Configure RetroArch as follows:
    - User Interface:
        (so that we don't get UI overlaid when screenshots are taken:)
        - On-Screen Notifications: Off
        - On-Screen Overlay: Off
        - Pause content When Not Active: Off
    - Video:
        (so that screenshots show the original pixels rather than being scaled up:)
        - GPU Screenshot: Off
    - Network:
        - Network Commands: On
        - User 1 Network RetroPad: On
    - Directory:
        - Screenshots: anything, but I needed this to not be blank

- Symlink `screenshots` to the previously chosen screenshots directory.

- Put a Gemini API key in `secrets/gemini_api_key.txt`.

    - See `poyo/openai.py` if you want to change the model.

- Load the included .gbc file into RetroArch (I used Gambatte core) and start the game.

- Commands you can run to make sure it's working:
    - `uv run python -m poyo.retroarch` to press A for 1 second
    - `uv run python -m poyo.yopo screenshot --annotated` to take a screenshot and add the overlay

- Start the HTTP server: `uv run python -m poyo.tailserver`

    - You can keep this running.

- Separately, run this to actually start controlling the game: `uv run python -m poyo.yopo ai`

    - This will start a new session in `log/log00.txt` (the name auto-increments).

    - To resume an existing session (i.e. context), pass the log file path as an additional argument after `ai`.

        - It's up to you to make sure RetroArch is actually in the same state as when the session left off.

- Then to watch the input/output live, go to:

  http://127.0.0.1:8002/frame.html

  or without the autoscrolling:

  http://127.0.0.1:8002/log/latest?render&tail
