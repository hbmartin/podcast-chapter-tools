DEFAULT = "default"


def prompt_transcript_to_chapters(transcript: str) -> dict[str, str]:
    default = (
        "I'm going to give you a podcast transcript with timestamps in this format: "
        "`(00:03:05) Some transcription`. with the timestamp in parentheses in HH:MM:SS format. "
        "Generate a list of all major topics covered in the podcast, "
        "and the timestamp where the discussion starts. Make sure to use the timestamp BEFORE the the discussion "
        "starts. Make sure to cover topics from the whole episode. Use this format: `(00:03:05) Topic name`. "
        "Make sure to use the first timestamp corresponding exactly to the start of the topic discussion in the "
        "transcript. Do not reformat or adjust the timestamps at all, use the exact on from the transcript. "
        "Do not write any preamble or text before the chapter list, only write the chapter list. "
        "Do not write anything before the timestamp in parentheses on each line. After you've done that, "
        "write a list of podcasts hosts (only if you know their names) On a single line as a comma separated list "
        "e.g.  Hosts: host1, etc. Then on a new line do the same for guests if there are any e.g. Guests: guest1, etc. "
        "On a newline, Write a comma separated list of major topics or entities discussed in the podcast. e.g. "
        "Topics: topic1, entity, etc."
        "Here's the transcript: \n\n"
        f"{transcript}"
    )

    return {DEFAULT: default}
