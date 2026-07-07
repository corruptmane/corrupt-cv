#let data = json(bytes(sys.inputs.at("data")))

#let accent-color = rgb("#2b4c7e")
#let muted-color = rgb("#555555")

#set document(
  title: data.personal_info.name + " — CV",
  author: data.personal_info.name,
)

#set page(
  paper: "a4",
  margin: (top: 1.8cm, bottom: 1.8cm, left: 2cm, right: 2cm),
)

#set text(
  font: "New Computer Modern",
  size: 10pt,
  lang: "en",
)

#set par(justify: true, leading: 0.65em)

#show heading.where(level: 1): it => {
  v(0.6em)
  text(size: 12pt, weight: "bold", fill: accent-color, upper(it.body))
  v(-0.4em)
  line(length: 100%, stroke: 0.5pt + accent-color)
  v(0.2em)
}

// --- Header ---

#align(center)[
  #text(size: 22pt, weight: "bold", fill: accent-color)[#data.personal_info.name]
  #v(-0.3em)

  #let contact-parts = ()
  #if data.personal_info.email != none {
    contact-parts.push(link("mailto:" + data.personal_info.email)[#data.personal_info.email])
  }
  #if data.personal_info.phone != none {
    contact-parts.push(data.personal_info.phone)
  }
  #contact-parts.push(data.personal_info.location_city + ", " + data.personal_info.location_country)

  #text(size: 9.5pt, fill: muted-color)[#contact-parts.join("  |  ")]

  #if data.personal_info.links.len() > 0 {
    v(-0.2em)
    let link-items = data.personal_info.links.map(l => {
      link(l.url)[#text(fill: accent-color)[#l.label]]
    })
    text(size: 9.5pt)[#link-items.join("  |  ")]
  }
]

#v(0.4em)

// --- Summary ---

#if data.summary != none and data.summary != "" {
  text(style: "italic", size: 10pt)[#data.summary]
  v(0.2em)
}

// --- Experience ---

#if data.experience.len() > 0 {
  heading(level: 1)[Experience]

  for exp in data.experience {
    grid(
      columns: (1fr, auto),
      align: (left, right),
      text(weight: "bold")[#exp.position #text(weight: "regular")[ at ] #exp.company],
      text(size: 9pt, fill: muted-color)[#exp.start_date #sym.dash.en #exp.end_date],
    )
    v(-0.3em)
    text(size: 9pt, fill: muted-color)[#exp.location]
    v(0.1em)
    text(size: 9.5pt)[#exp.description]

    if exp.highlights.len() > 0 {
      v(0.1em)
      for hl in exp.highlights {
        block(inset: (left: 1em))[
          #text(size: 9.5pt)[#sym.bullet.op #h(0.3em) #hl]
        ]
      }
    }
    v(0.4em)
  }
}

// --- Education ---

#if data.education.len() > 0 {
  heading(level: 1)[Education]

  for edu in data.education {
    grid(
      columns: (1fr, auto),
      align: (left, right),
      text(weight: "bold")[#edu.degree in #edu.field],
      text(size: 9pt, fill: muted-color)[#edu.start_date #sym.dash.en #edu.end_date],
    )
    v(-0.3em)
    text(size: 9.5pt)[#edu.institution]

    if edu.gpa != none {
      text(size: 9pt, fill: muted-color)[ — GPA: #str(edu.gpa)]
    }

    if edu.highlights.len() > 0 {
      v(0.1em)
      for hl in edu.highlights {
        block(inset: (left: 1em))[
          #text(size: 9.5pt)[#sym.bullet.op #h(0.3em) #hl]
        ]
      }
    }
    v(0.4em)
  }
}

// --- Skills ---

#if data.skills.len() > 0 {
  heading(level: 1)[Skills]

  for skill in data.skills {
    block(spacing: 0.5em)[
      #text(weight: "bold", size: 9.5pt)[#skill.category:] #text(size: 9.5pt)[#skill.items.join(", ")]
    ]
  }
  v(0.2em)
}

// --- Projects ---

#if data.projects.len() > 0 {
  heading(level: 1)[Projects]

  for proj in data.projects {
    let name-display = if proj.url != none {
      link(proj.url)[#text(weight: "bold")[#proj.name]]
    } else {
      text(weight: "bold")[#proj.name]
    }

    [#name-display]
    if proj.technologies.len() > 0 {
      h(0.5em)
      text(size: 8.5pt, fill: muted-color)[#proj.technologies.join(" · ")]
    }
    linebreak()
    text(size: 9.5pt)[#proj.description]
    v(0.4em)
  }
}

// --- Languages ---

#if data.languages.len() > 0 {
  heading(level: 1)[Languages]

  let lang-items = data.languages.map(l => {
    [#text(weight: "bold")[#l.name] (#lower(l.proficiency))]
  })
  lang-items.join("  |  ")
}
