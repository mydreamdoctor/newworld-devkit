/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

#include "NWCapitalModule.h"
#include <NWCapital/Components/CapitalCookieGradientComponent.h>

namespace NWCapital
{
    NWCapitalModule::NWCapitalModule()
    {
        m_descriptors.insert(m_descriptors.end(), {
            CapitalCookieGradientComponent::CreateDescriptor(),
        });
    }

    AZ::ComponentTypeList NWCapitalModule::GetRequiredSystemComponents() const
    {
        return AZ::ComponentTypeList{};
    }
}

#if !defined(NWCAPITAL_GEM_EDITOR)
#if defined(O3DE_GEM_NAME)
AZ_DECLARE_MODULE_CLASS(AZ_JOIN(Gem_, O3DE_GEM_NAME), NWCapital::NWCapitalModule)
#else
AZ_DECLARE_MODULE_CLASS(Gem_NWCapital, NWCapital::NWCapitalModule)
#endif
#endif
