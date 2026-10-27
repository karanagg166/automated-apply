"""Owned multiple-choice widgets; no real employer or remote account."""


def application(
    kind="select", *, mode="normal", required=True, consent=True, preselected=True
):
    title = "I agree to privacy terms" if mode == "consent" else "Technical skills"
    labels = ["Python", "FastAPI", "Go"]
    if mode == "duplicate":
        labels[1] = "Python"
    codes = (
        ["python", "fastapi", "go"]
        if mode != "duplicate-values"
        else ["same", "same", "go"]
    )
    needed = "required" if required else ""
    if kind == "select":
        widget = f"<label>{title}<select id=choices name=choices multiple {needed}>"
        for label, code in zip(labels, codes):
            widget += f'<option value="{code}" {"selected" if preselected and label == "Go" else ""}>{label}</option>'
        widget += "</select></label>"
    elif kind == "checkbox":
        widget = f'<fieldset id=choices aria-required="{str(required).lower()}"><legend>{title}</legend>'
        for label, code in zip(labels, codes):
            individual = "required" if mode == "individual" else ""
            widget += f'<label>{label}<input id="{code}" type=checkbox name=choices value="{code}" {"checked" if preselected and label == "Go" else ""} {individual}></label>'
        widget += "</fieldset>"
    else:
        widget = f'<div id=choices role=group aria-label="{title}" aria-required="{str(required).lower()}">'
        for label, code in zip(labels, codes):
            checked = "true" if preselected and label == "Go" else "false"
            widget += f"<button id=\"{code}\" type=button role=checkbox data-value=\"{code}\" aria-label=\"{label}\" aria-checked=\"{checked}\" onclick=\"this.setAttribute('aria-checked',this.getAttribute('aria-checked')==='true'?'false':'true');this.dispatchEvent(new Event('change',{{bubbles:true}}))\">{label}</button>"
        widget += "</div>"
    html = (
        "<h1>Example Circuit — Backend Engineer multiple fixture</h1><form method=post action=/receipt><label>Full name<input name=name required></label>"
        + widget
    )
    html += "<label>Email<input name=email type=email required></label>"
    if consent:
        html += "<label>I consent to data processing<input id=consent type=checkbox required></label>"
    if mode == "step":
        html += "<button type=button onclick=\"document.forms[0].innerHTML='<label>Availability date<input type=date required></label><button type=submit>Apply</button>'\">Next step</button>"
    else:
        html += "<button type=submit>Apply</button>"
    html += "</form><script>"
    if mode == "readonly":
        html += "document.getElementById('choices').setAttribute('aria-readonly','true');"
    if mode == "submit-control":
        html += "document.querySelectorAll('#choices button').forEach(e=>e.type='submit');"
    if mode == "dynamic":
        html += "document.getElementById('choices').addEventListener('change',()=>{const e=document.createElement('input');e.required=true;e.setAttribute('aria-label','New dependent question');document.forms[0].append(e)},{once:true});"
    if mode == "network":
        html += "document.getElementById('choices').addEventListener('change',()=>fetch('/save-draft?multi=1').catch(()=>{}));"
    if mode == "invalid":
        html += "const e=document.getElementById('choices');if(e.tagName==='SELECT')e.setCustomValidity('Fictional validation');else e.setAttribute('aria-invalid','true');"
    return html + "</script>"
