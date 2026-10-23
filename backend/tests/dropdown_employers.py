"""Owned transient/dropdown fixtures; manual network loading is explicit in tests."""


def application(*, button=False, mode="local"):
    control = (
        '<button type=button id=city role=combobox aria-label="Preferred city" aria-expanded=false>Choose city</button>'
        if button
        else '<input type=text readonly id=city role=combobox aria-label="Preferred city" aria-expanded=false required>'
    )
    return (
        """<h1>Example Circuit — Backend Engineer dropdown fixture</h1><form method=post action=/receipt>
        <label>Full name<input name=name required></label>"""
        + control
        + """<input type=hidden name=city_code id=city-code>
        <label>Email<input name=email type=email required></label>
        <label>I consent to data processing<input id=consent type=checkbox required></label>
        <button type=submit>Submit application</button></form><script>"""
        + f"window.fixtureMode='{mode}';"
        + """
        window.fixtureChoices=['Pune','Bengaluru'];window.fixtureOpens=0;
        const city=document.getElementById('city');
        function closeCity() {
          if(window.fixtureMode==='unclosable') return;
          document.getElementById('city-options')?.remove();
          city.setAttribute('aria-expanded','false');city.removeAttribute('aria-controls');
        }
        city.addEventListener('keydown',e=>{if(e.key==='Escape') closeCity()});
        city.addEventListener('click',async()=>{
          if(city.getAttribute('aria-expanded')==='true'){closeCity();return}
          window.fixtureOpens++;
          city.setAttribute('aria-expanded','true');city.setAttribute('aria-controls','city-options');
          const list=document.createElement('ul');list.id='city-options';list.setAttribute('role','listbox');
          if(window.fixtureMode==='multi') list.setAttribute('aria-multiselectable','true');
          document.body.append(list);
          if(window.fixtureMode==='mutate') document.getElementById('consent').checked=true;
          if(window.fixtureMode==='submit') document.forms[0].requestSubmit();
          if(window.fixtureMode==='get') fetch('/save-draft?source=dropdown').catch(()=>{});
          let options=window.fixtureChoices;
          if(window.fixtureMode==='remote') {
            try {
              if(!window.fixtureCached) window.fixtureCached=await (await fetch('/choice-options')).json();
              options=window.fixtureCached;
            } catch {return}
          }
          if(window.fixtureMode==='ambiguous') options=['Pune','Pune'];
          if(window.fixtureMode==='consent') options=['I agree to privacy terms','No'];
          if(window.fixtureMode==='delayed') await new Promise(r=>setTimeout(r,100));
          for(const label of options) {
            const option=document.createElement('li');option.setAttribute('role','option');option.textContent=label;
            if(window.fixtureMode==='disabled') option.setAttribute('aria-disabled','true');
            option.addEventListener('click',()=>{
              if(city.tagName==='INPUT') city.value=label;else city.textContent=label;
              document.getElementById('city-code').value=label.toLowerCase();
              closeCity();
              if(window.fixtureMode==='dependent') {
                const extra=document.createElement('input');extra.setAttribute('aria-label','New dependent question');extra.required=true;document.forms[0].append(extra);
              }
            });list.append(option);
          }
        });</script>"""
    )
