
# Benchmark Articles Content

# 1. Long Article (~2000 chars - "Long" for this context, normally would be longer but sufficient for relative timing)
# Topic: History/General
ARTICLE_LONG = {
    "id": "long_01",
    "url": "https://example.com/history-printing",
    "source_id": "historical_review",
    "title": " The Evolution of the Printing Press: A Revolution in Knowledge",
    "content": """
    The printing press is often cited as one of the most influential inventions in human history. Before its creation by Johannes Gutenberg around 1440, books were painstakingly copied by hand, making them expensive and rare. Knowledge was the domain of the elite, locked away in monasteries and royal libraries. 

    Gutenberg's innovation wasn't just the press itself, but the combination of movable type, oil-based ink, and a wooden screw press similar to agricultural wine presses of the period. This system allowed for the mass production of books at a fraction of the cost. The Gutenberg Bible, printed in the 1450s, demonstrated that a printed book could rival the aesthetic quality of a handwritten manuscript while being produced much faster.

    The impact was immediate and profound. By 1500, printing presses were in operation throughout Western Europe, having produced more than twenty million volumes. In the 16th century, with presses spreading further afield, their output rose to an estimated 150 to 200 million copies. This explosion of printed matter facilitated the spread of the Renaissance, the Reformation, and the Scientific Revolution.

    For the first time, scientific data could be shared accurately across borders. Medical texts with anatomical drawings, astronomical tables, and engineering diagrams could be replicated without the errors inherent in hand copying. This standardized knowledge base allowed scientists to build directly upon each other's work, accelerating the pace of discovery.

    Furthermore, the printing press played a crucial role in standardization of languages. As printers sought to reach the widest possible audience, they favored vernacular languages over Latin, helping to codify grammar and spelling. This rise of vernacular literature fostered national identities and literacy among the growing middle class.

    In the modern era, we see parallels with the digital revolution. Just as the printing press democratized access to information, the internet has further lowered the barriers to publishing and distribution. However, the core principle remains: the ability to disseminate ideas rapidly and cheaply is a fundamental driver of societal change. 

    Critics of the time feared that the easy availability of books would lead to intellectual laziness or the spread of dangerous ideas. Indeed, the press was used to propagate propaganda and dissent. Yet, it also enabled the public sphere, a space for debate and the exchange of ideas that is essential for democracy. 

    The legacy of the printing press is undeniable. It transformed the economy of knowledge from one of scarcity to one of abundance. It shifted power structures, challenged authorities, and empowered individuals. As we navigate the current information age, understanding this historical pivot point offers valuable context for the challenges and opportunities of our own time.
    """ * 2 
}

# 2. Medium Article (~800 chars)
# Topic: News/Discovery
ARTICLE_MEDIUM = {
    "id": "med_01",
    "url": "https://example.com/frog-discovery",
    "source_id": "nature_daily",
    "title": "New Species of 'Silent' Frog Discovered in Cloud Forests",
    "content": """
    Biologists exploring the dense cloud forests of the Andes have identified a remarkable new species of frog that does not croak. Unlike most anurans that rely on vocal calls to attract mates, this species, named *Centrolene mutum*, appears to communicate using visual signaling.
    
    The discovery was made during a three-week expedition to a remote valley previously inaccessible due to rough terrain. "We noticed them waving their hands," said Dr. Elena Gomez, the lead herpetologist. "It's a behavior known as foot-flagging, often seen in species living near loud waterfalls, but these frogs live in quiet streams."
    
    Genetic analysis confirms that *C. mutum* is distinct from its closest relatives, diverging approximately 2 million years ago. The frogs possess translucent skin on their undersides, a characteristic of glass frogs, revealing their beating hearts.
    
    Conservationists are urging for immediate protection of the area. The valley is currently threatened by illegal logging operations. "This species is a clear indicator of the region's biodiversity," noted Gomez. "If we lose the forest, we lose a lineage that evolved a unique solution to communication."
    
    The team plans to return next year to study the frog's mating rituals in detail and assess the population size. Early estimates suggest fewer than 500 individuals remain in the wild.
    """
}

# 3. Technical Article (~1000 chars, dense inputs)
# Topic: Scientific/Data
ARTICLE_TECHNICAL = {
    "id": "tech_01",
    "url": "https://example.com/battery-efficiency",
    "source_id": "journal_chem_phys",
    "title": "Solid-State Battery Efficiency Exceeds 90% in Low Temperature Trials",
    "content": """
    Abstract: We report on a novel lithium-metal solid-state battery architecture utilizing a sulfide-based electrolyte (Li10GeP2S12) doped with zirconium. 
    
    Experimental Results:
    The prototype cells demonstrated a Coulombic efficiency of 99.8% over 500 cycles at room temperature (25°C). Remarkably, at -20°C, the cells retained 91.5% capacity, a significant improvement over standard Li-ion counterparts which typically drop to <60%.
    
    Specific energy density was measured at 450 Wh/kg, while power density reached 1.2 kW/kg. 
    Impedance spectroscopy reveals that the Zr-doping significantly reduces the interfacial resistance at the cathode-electrolyte boundary (R_ct dropped from 120 Ω cm² to 35 Ω cm²).
    
    X-ray diffraction (XRD) patterns confirm the stability of the crystal structure after deep cycling. No dendritic growth was observed via Scanning Electron Microscopy (SEM) up to a current density of 2.5 mA/cm².
    
    Conclusion:
    These metrics suggest that sulfide-based electrolytes, when properly stabilized, correct the poor low-temperature performance historically associated with solid-state batteries. This represents a viable pathway for automotive applications in cold climates.
    """
}

ALL_ARTICLES = [ARTICLE_MEDIUM, ARTICLE_TECHNICAL]
