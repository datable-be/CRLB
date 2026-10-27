from peft import AutoPeftModelForCausalLM
from transformers import AutoTokenizer
model_id='pbevan11/llama-3.1-8b-ocr-correction'
model = AutoPeftModelForCausalLM.from_pretrained(model_id).cuda()
tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token


def prompt(instruction, inp):
    return f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{instruction}

### Input:
{inp}

### Response:
"""


def prompt_tok(instruction, inp, return_ids=False):
    _p = prompt(instruction, inp)
    input_ids = tokenizer(_p, return_tensors="pt", truncation=True).input_ids.cuda()
    out_ids = model.generate(input_ids=input_ids, max_new_tokens=5000,
                             do_sample=False)
    ids = out_ids.detach().cpu().numpy()
    if return_ids: return out_ids

    full_output = tokenizer.batch_decode(ids, skip_special_tokens=True)[0]
    response_start = full_output.find("### Response:")
    if response_start != -1:
        return full_output[response_start + len("### Response:"):]
    else:
        return full_output[len(_p):]

# model inputs
instruction = "You are an assistant that takes a piece of text that has been corrupted during OCR digitisation, and produce a corrected version of the same text."
# inp = "Do Not Kule Oi't hy.er-l'rieed AjijqIi: imac - Analyst (fteuiers) Hcuiers - A | ) | ilf, <;/) in |) nter |iic . conic! deeiilf. l.o sell n lower-|)rieofl wersinn oi its Macintosh cornutor to nttinct ronsnnu-rs already euami'red ot its iPod music jiayo-r untl annoyoil. by sccnrit.y problems ivitJi Willtlows PCs , Piper.iaffray analyst. (Jcne Muster <aid on Tlinrtiday."
inp = "Pierre Bautier, Les esquisses d e R ubens au M u sée d e B ru xelles"

# print prediction
out = prompt_tok(instruction, inp)
print(out.replace('\\', ' ').strip('\\n'))
