import replicate

def caption_image(img):
    resp = replicate.run(
        "salesforce/blip:2e1dddc8621f72155f24cf2e0adbde548458d3cab9f00c0139eea840d0ac4746",
        input={"image": img}
    )
    return re.sub("^Caption: ", "", resp).capitalize()

def read_text(text, voice="mol", custom_voice=None):
    model = "afiaka87/tortoise-tts:e9658de4b325863c4fcdc12d94bb7c9b54cbfe351b7ca1b36860008172b91c71"
    inp = {"text": text,
           "voice_a": voice,
           "voice_b": "disabled",
           "voice_c": "disabled"}
    if custom_voice is not None:
        with open(custom_voice, "rb") as voice_file:
            final_inp = {**inp, **{"voice_a": "custom_voice", "custom_voice": voice_file}}
            return replicate.run(model, input=final_inp)
    else:
        return replicate.run(model, input=inp)
