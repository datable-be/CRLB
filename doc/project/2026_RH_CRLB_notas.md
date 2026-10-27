

# **CRLB \- AI data-extractie**

Nota's

|  |  |
| ----- | ----- |
|  |  |

| document properties |  |  |  |
| :---- | :---- | :---- | :---- |
| **title** | CRLB \- AI data-extractie |  |  |
| **project** |  |  |  |
| **document history** | **date** | **name** | **notes** |
|  | Datum |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |

**Inhoud**

[**Beschrijving volgens offerte	3**](#beschrijving-volgens-offerte)

[WP 5.2 Extractie Corpus Rubenianum (fase 1\)	3](#wp-5.2-extractie-corpus-rubenianum-\(fase-1\))

[**Brondata	6**](#brondata)

[4.1. Inhoud	6](#4.1.-inhoud)

[4.1.1. Overzicht	6](#4.1.1.-overzicht)

[4.1.2. Structuur	6](#4.1.2.-structuur)

[4.3. Technische aspecten	8](#4.3.-technische-aspecten)

[4.3.1. Beschikbaarheid van de data	8](#4.3.1.-beschikbaarheid-van-de-data)

[4.3.2. Geautomatiseerde data extractie	8](#4.3.2.-geautomatiseerde-data-extractie)

[**Datastructuur	9**](#datastructuur)

[Datamodel RO	9](#datamodel-ro)

[Instructies	9](#instructies)

# **Beschrijving volgens offerte** {#beschrijving-volgens-offerte}

| WP 5.2 Extractie Corpus Rubenianum (fase 1\) |  |  |  |  |  |  |
| :---- | :---- | ----- | :---- | ----- | :---- | ----- |
| Data worden uit de pdf-versies van het Corpus Rubenianum geëxtraheerd in gestructureerde vorm. Het gaat hierbij om de gegevens die niet (volledig) manueel werden toegevoegd: provenance tentoonstellingshistoriek bibliografische gegevens beschrijvende teksten Op beschrijvende teksten wordt een verrijking uitgevoerd. Verrijking betreft onder meer het herkennen van named entities (bv. mythologische figuren, plaatsnamen) en het koppelen van de entities aan de door het dataprofiel gedefinieerde authorities (bijvoorbeeld Iconclass). Voor entity recognition kan gebruik worden gemaakt van de indexen van het Corpus.  De data-extractie en eventuele verrijking gebeuren met behulp van generatieve AI (LLM).  Dit omvat de volgende subtaken: mapping opstellen (tekstelementen naar datamodel Rubens Online) extractie data en entities verrijken van entities  |  |  |  |  |  |  |
| resultaat | inhoud van het Corpus is beschikbaar in gestructureerd dataformaat, compatibel met het dataprofiel van Rubens Online |  |  |  |  |  |
| start  | 2026-09-01 |  | eind |  | 2027-01-31 |  |

* De specificaties van deze opdracht werden beschreven in een afzonderlijk document. (zie Bijlage CRLB2RO)  
* Een aantal volumes zijn in een lagere kwaliteit gescand (pagina's niet rechtgetrokken e.d.) De kwaliteit van deze scans wordt onderzocht en \- indien deze onvoldoende blijkt \- worden de originelen opnieuw gedigitaliseerd.

Aanpak Datable:

* OCR optimalisatie:  
  * Aangezien de beschikbare OCR resultaten niet optimaal zijn, geven we de voorkeur aan het opnieuw uitvoeren van de OCR met een gespecialiseerd LLM (bv. Baidu-OCR-Unlimited) of te corrigeren (zoals voorgesteld in 03788 BIJLAGE CRLB2RO). Voorafgaand wordt de kwaliteit van de huidige OCR gemeten door het berekenen van de word error rate (WER) van een sample uit de corpusdelen. Op basis daarvan wordt de meest aangewezen aanpak bepaald.  
  * Indien hiermee niet de gewenste kwaliteit wordt bereikt, kan in overleg met de opdrachtgever worden besloten het originele volume opnieuw te digitaliseren. Deze taak valt buiten de scope van dit WP.  
* We analyseren de structuur van elk corpusdeel en identificeren de te verwerken delen:  
  * De opbouw van de eigenlijke entries en identificatie van de te extraheren gegevens (op basis van het RO Datamodel).  
  * De registers e.d., die mogelijk voor extra controle kunnen worden gebruikt (bv. voor NER).  
* Referentiedata:  
  * Op basis van de analyse, datamapping en reeds aanwezige data in RKD/Axiell, worden referentierecords aangemaakt. Deze referentierecords worden gebruikt voor controle, evaluatie en ontwikkeling van de AI prompt.  
  * Op basis van beschikbare data in RKD/Axiell en registers uit de corpusdelen worden controlelijsten gemaakt  
* Er wordt een modulaire architectuur ontwikkeld voor het verwerken van de corpusdelen. Deze architectuur bestaat uit:  
  * File storage voor het tijdelijk bewaren van PDF bestanden (bv. Hetzner bucket).  
  * Een cloud based database applicatie (bv. NocoDB) voor het bewaren en publiceren van teksten uit het corpus ('entries') \- dit in afwachting van een definitieve oplossing in de Oeuvredatabase, in fase 2 (cf. WP 5.7 Opzetten applicatie voor CRLB entries).   
  * Database voor het tijdelijk opslaan van controlelijsten, geëxtraheerde data en verrijkte data (bv. MongoDB)  
  * AI component voor OCR module (met behoud van de documentstructuur) en opdelen van OCR tekst in entries. Resultaten worden weggeschreven als Markdown files naar de tekstendatabase.  
  * AI module voor het extraheren van gestructureerde data (incl. de embedded Permalink), weggeschreven als JSON.  
  * Component voor het normaliseren van geëxtraheerde gegevens op basis van controlelijsten en invoerinstructies.  
  * Component voor het verrijken van geëxtraheerde gegevens met een LOD URI.

  Bij het ontwikkelen van deze architectuur baseren we ons op de state of the art modellen en expertise, die we waar nodig afstemmen met specialisten in dit domein.[^1] 

	![][image1]

Opmerkingen:

* Omdat de structuur van de verschillende corpusdelen licht afwijkt, wordt elke fase van de procedure voor elk corpusdeel getest, geëvalueerd en waar nodig bijgesteld.  
* Teksten die niet vereist zijn voor data-extractie (bv. inleidingen en essays) worden indien gewenst wel verwerkt in functie van OCR optimalisatie.

Inschatting werklast:

* Analyse, mapping, referentierecords: 	3 MD   
* OCR optimalisatie	5 MD  
* Creëren controlelijsten	3 MD  
* Opzetten architectuur	15 MD  
* Uitvoeren, controle en evaluatie	10 MD  
* Overleg, documentatie en rapportage	4 MD  
  Totaal:	40 MD

Kennisdeling:

* Scripts die voor dit werkpakket werden ontwikkeld, worden onder een open licentie gedeeld via Github.  
* Documentatie van de gebruikte procedures, scripting en architectuur.  
* De opdrachtgever wordt bij elke fase nauw betrokken in functie van de evaluatie.  
* Uitgebreide toelichting in Workshop 2 (zie verder)

# **Brondata** {#brondata}

Beschikbare Corpusdelen: [https\://rubenshuis.be/nl/corpus-rubenianum-ludwig-burchard](https://rubenshuis.be/nl/corpus-rubenianum-ludwig-burchard)

## **4.1. Inhoud** {#4.1.-inhoud}

### **4.1.1. Overzicht** {#4.1.1.-overzicht}

Het Corpus Rubenianum Ludwig Burchard (CRLB)  bevat een compleet overzicht van het oeuvre van Rubens. Het telt meer dan 2.500 composities en ongeveer 15.000 kunstwerken, waaronder schilderijen, tekeningen, prenten en wandtapijten die onder Rubens' supervisie zijn geproduceerd en (kwalitatieve) kopieën naar zijn composities.[^2] De publicatie bestaat uit een reeks wetenschappelijke delen, die elk gewijd zijn aan een specifiek thema binnen het oeuvre. .  
Van de geplande 49 delen zijn er intussen 44 verschenen. Delen kunnen uit meerdere volumes bestaan. Na het vervolledigen van de reeks zal er worden gewerkt aan de addenda en corrigenda (met name werken van Rubens die door de auteurs over het hoofd werden gezien, pas later als zodanig werden erkend en/of ontdekt). 

### **4.1.2. Structuur** {#4.1.2.-structuur}

Elk deel in de reeks volgt een gelijkaardige opbouw zie illustratie):

* Inleiding en achtergrondinformatie. In de eerste delen zijn de inleidende essays vrij beperkt. In latere delen werden er meer uitgebreide, contextualiserende essays geschreven.   
* Catalogus: Beschrijving van de individuele werken, inclusief:  
  * Technische details en verwijzing naar afbeeldingen  
  * Provenance (herkomstgeschiedenis)  
  * Toeschrijving en datering  
  * Stijl- en materiaalanalyse  
  * Vergelijking met andere werken

  De beschrijvingen volgen geen vaste structuur. Ze bevatten wel voetnoten en bibliografische referenties.

* Afbeeldingen  
* Bijlagen: extra secties waarin relevante documenten of discussies worden aangeboden.  
* Indexen  
* Bibliografie (literature)  
* Tentoonstellingen

De catalogus vermeldt voor elk werk de volgende gegevens:

| CRLB | voorbeeld\_bron | note |
| :---- | :---- | :---- |
| \[RKD URL\] | [https\://rkd.nl/images/23131](https://rkd.nl/images/23131)  | een verwijzing naar het overeenkomstig record in RKDimages. Deze url is embedded in de PDF, maar niet vermeld in de gedrukte publicatie |
| \[nummer\] | 1 1a (1) 1-1 | een doorlopende nummering. Stadia in compositie (tekening, olieverfschets) worden aangeduid met suffix a, b etc. Kopieën worden aangeduid met een volgnummer (1), (2) etc. Fragmenten (van werken die versneden werden) krijgen eigen catalogusnummers (1-1, 1-2 enz.). |
| \[titel\] | Views of Rome: A Trattoria in the Baths of Diocletian and the former Abbey of Santa Sabina in Aventino |  |
| \[type\] | painting, oil sketch, drawing, tapestry, … |  |
| beeldverwijzing | (Fig. 1\) | Verwijzing naar een afbeelding verder in het deel , bv. 'Fig. 50' |
| \[materiaal, techniek\] | Oil on canvas; | gewenst is dit op te delen in  'drager' en 'techniek' |
| afmetingen | 193 x 207 cm. |  |
| inscripties en merken | In the upper part below on the right, the numbers 6 and 249; in the lower part, below on the left, the number A 2714\. |  |
| locatie | Amsterdam, Collection of Professor J . Q. van Regieren Altena. Madrid, Prado. No. 17x4 (as Jan Eyck). | Huidige locatie, met plaatsnaam en bemerkingen |
| datering |  |  |
| technical notes |  | een beschrijving zijn van de toegepaste techniek, van conditie en/ofrestauratiegeschiedenis. Deze sectie komt voort uit de summiere technische beschrijving die in oudere delen werd gegeven samen met de drager en afmetingen. |
| provenance | Real Academia de San Fernando, Madrid (in 1796 ?); | chronologische opsomming van de herkomst, met naam van de collectie, plaatsnaam en datering. Collectie- en veilinggegevens worden door elkaar genoteerd (itt. RKDimages) |
| exhibition | Bayonne, 1965, No. 28 (repr.). | met locatie, datum en nummer |
| literature | Rooses, iii, pp. 9, 10, No. 501 (as Jan van Eyck); |  |
| beschrijving | The painting represents the final moments of Apollo’s vain pursuit of Daphne, who had denied Apollo’s love and fled. JuSt as the god was about to reach her, she was changed into a laurel tree (Ovid, Met., I, 452-552). In copying Rubens’s sketch, the painter has... |  |

Ondanks de sterke mate van structuur in de publicatie, zijn er een aantal hindernissen bij het gebruik van het CRLB als gestructureerde bron:

* De criteria voor het opnemen van kopieën verschilt naargelang auteur.  
* Teksten vooraan in het boek zijn algemeen van aard (niet rechtstreeks met betrekking tot een bepaald werk of compositie). Er is nog geen beslissing over de vraag of en hoe deze teksten als bron worden opgenomen.  
* Trefwoorden (zoals eigennamen, bv. Duke of ...) zijn niet consequent genoteerd doorheen de volumes.

## **4.3. Technische aspecten** {#4.3.-technische-aspecten}

### **4.3.1. Beschikbaarheid van de data** {#4.3.1.-beschikbaarheid-van-de-data}

* De gepubliceerde volumes zijn digitaal beschikbaar:  
  * De volumes verschenen vóór 1997 (d.w.z. tot en met XIII (1). Subjects from History) werden door een extern bedrijf gedigitaliseerd.  
  * De daaropvolgende boeken werden (vermoedelijk) in huis gedigitaliseerd, met een (vermoedelijk) lagere kwaliteit. De volumes XXVI (2.2) en XXVI (2.3) (2011) zijn problematisch: de tekst buigt aan de marges, waardoor OCR mogelijk minder goed werkt.  
  * Vanaf 2014 (d.w.z. deel V (1). The Life of Christ before the Passion: the Youth of Christ) beschikt het Rubenshuis over een born digital pdf.  
* In de pdf-bestanden die langer dan 15 jaar geleden werden gepubliceerd, werden koppelingen toegevoegd die verwijzen naar RKDimages. Die bestanden worden bewaard in het DAMS van de stad Antwerpen (zie verder) en beschikbaar gemaakt op de website van het Rubenshuis.[^3] 

### **4.3.2. Geautomatiseerde data extractie** {#4.3.2.-geautomatiseerde-data-extractie}

* Tijdens een hackathon georganiseerd in het kader van het AI4Culture project, werd in februari 2025 een oplossing ingediend (['Un2Structured'](https://pro.europeana.eu/post/how-ai-is-transforming-digital-cultural-heritage), van Arnoud Wils). Dit project had als doel gestructureerde JSON-data te extraheren uit ongestructureerde PDF-bestanden van het Corpus Rubenianum, met een focus op herkomst en iconografie-informatie. Het team achter 'Un2Structured' maakte gebruik van Llamaparse, Llamaindex, de Cohere LLM API en Pydantic voor data-extractie en \-structurering. Met de het team werd afgesproken een voortzetting van dit project te onderzoeken, waarbij in de eerste plaats de technische eisen zouden worden vastgesteld.  
* Een alternatieve mogelijkheid werd onderzocht, waarbij voor elke entry in de catalogus de url met verwijzing naar RKDimages en het paginanummer wordt geëxtraheerd, samen met een extract van de pdf. Op basis van deze extractie zou een verwijzing naar het CRLB en/of voorvertoning van de entry aan RKDimages kunnen worden gekoppeld.

Bij deze extractie moet met een aantal elementen rekening worden gehouden:

* De delen van het CRLB zijn beschikbaar in PDF-formaat, hetzij als scans van de gedrukte versie of als  born-digital PDF. De OCR kwaliteit is niet optimaal, waardoor er correcties vereist zijn in woordgebruik, cijfers, afkortingen en spatiëring, bv.:  
  Madrid, Prado. No. 17x4 (as Jan Eyck).	  
  Pierre Bautier, Les esquisses d e R ubens au M u sée d e B ru xelles,  
* Teksten bevatten ook voetnoten en bibliografische referenties. Vraag is hoe dit geëxtraheerd kan worden en vervolgens gestructureerd. Eén mogelijkheid is het structureren van de teksten m.b.v. [TEI](https://tei-c.org). Deze standaard ondersteunt het gebruik van voetnoten en andere verwijzingen. Een mogelijk alternatief is het gebruik van Markdown;  
* Indexen kunnen mogelijk gebruikt worden voor inhoudelijke ontsluiting van entries en teksten.  
* Het is gewenst het toevoegen van embedded URL's verder te zetten voor de hoofdnummers (niet de kopieën), omdat gebruikers (met name onderzoekers) ook vanuit de publicatie kunstwerken willen kunnen opzoeken. 

# **Datastructuur** {#datastructuur}

## **Datamodel RO** {#datamodel-ro}

* Browsable versie: [https\://hvanstappen.github.io/RubensOnline](https://hvanstappen.github.io/RubensOnline)   
* Tabel: [2025\_RO\_datamodeling](https://docs.google.com/spreadsheets/d/1t_Tt4jtfaT1j-gEBEcGngK_qcSTe3TC07R4XQUFudys)

Status:

* Datamodel wordt geïmplementeerd in datahub van stad Antwerpen  
* Nog goed te keuren door opdrachtgever

## **Instructies** {#instructies}

* Author guidelines CRLB:   
  * [20151015\_CRLB\_Editorial\_Style\_Guide.pdf](https://drive.google.com/file/d/1sG_Xp6tBvBxngor7wXRWSbhPn_esMBdA/view?usp=drive_link)  
  * [20151015\_CRLB\_Bibliography\_new\_rules.pdf](https://drive.google.com/file/d/1oCTW55lQNygxIXALATStWQG7_ArWfczc/view?usp=drive_link)

  *"Ik merk op dat de documenten niet meer zijn bijgewerkt sinds 2015, en ook nooit echt volledig toegepast. Dit kan mogelijks een beperking vormen bij het gebruik ervan als hulpmiddel."*

* Invoer RKD: [Handleiding\_RKDdatabases (15).pdf](https://drive.google.com/file/d/1zJRGpA29p6zto5z-oTxdYRw8EsBmWvlf/view?usp=drive_link)

[^1]:  zie referenties.

[^2]:  De richtlijn is om alle kopieën op te nemen. In het verleden werd er geselecteerd op basis van kwaliteit, maar vandaag zeker niet meer.

[^3]:  [https\://rubenshuis.be/nl/corpus-rubenianum-ludwig-burchard](https://rubenshuis.be/nl/corpus-rubenianum-ludwig-burchard) 

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAZ0AAAGLCAYAAAAcUE8kAABBx0lEQVR4Xu3dB7jUVN4/8ABSBSlSRBFFQVFQwboWxIKVXdnX8tp1lRUEXbtgWVFc26pgWX3t5RXr2ruy4p8F9rUgTbCAAtK7gPR6/vmem5N75ndn7p25SaYk38/znCfJSSblTE5+k0xy4jhERERERERERERERERERERERERERERERJQH+7lJVZK+c1Ndf2oiIqJqmOlUDDBVpav1J4mIiLLkB5ErrrhCZWPLli1qhx12sIPPMylzJCIiEjY5XtDYuHGjjCtZ69u3rx18iIiIKtBB4uOPP5YxpNrq1KljAs8QsSwiIkqohm5SNWrUkDEjFIMHDzaB5wuxXCIiSiAdFKK0bt06E3g+E8smIqIEiewMR3rjjTdM4BknV4KIiOJvsxPxGY7Utm1bE3hwSY+IiBJiRzep9evXy7gQuZo1a/KuNiKihIn8f5zKeMs/QawTERHFkL5brZCsh0iJiCjmCnqWY3jrUUusGxERxYx65513ZAzIO6yHmxbLlSMioniRx/+C2G233XiJjYgo5v7qFEnQmTZtGoMOEVHMrXSqGXRGjx4ts9Lq0aOHzMoI6yJXkIiI4mOjk2XQwXQdO3b0WyyoXbu26tatmz+uU6dO/g0JBxxwgL4j7f7779d5ZrqqYFp75YiIKF78QFEV2TxOq1atUoahZ8+eunvooYf6ednOH7z1ISKimNrq5BAU+vTp4wcRE3RWr16tunTpolszOO2003Qegw4REaWzzskyKPz1r3/V3a1bt6pJkyb5Qefzzz/3m8/ZZpttdJdBh4iI0vnSyTIoLF26VDVu3Fi99957fp75LC6rDR06VAck5NlBZ82aNapu3br+cCbLly9n0CEiSgB5/C+IW265hUGHiCgB1JYtW2QMyDush5eIiCjGVOvWrWUMyDush5uayZUjIqJ4udYp8CU23KSAdZArRkRE8aT69esnY0HeYPlumiJXioiI4uk5p0BnO3/60594lkNElECqTp06MiZE6ocffjAB5065MkREFH/qjjvukLEhMliel4iIKIEedJPauHGjjA+hw3K8RERECaaDwYYNG2ScCI1ZhlguEREllG4I9JNPPpHxIjDM10tERES+8Y4XIMJg3aXGgENERGk1dLxAUbNmTbVp0yYZS6pktamGdFfK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>